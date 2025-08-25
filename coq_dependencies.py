import re
from dot_parsing import CoqGraph, coq_files_graph_from_dotfile, coq_signature_graph_from_dotfile
from coq_filedep import run_coqdep
from coq_sercomp import iter_sentences
from coq_modules import parse_coq_project_file, CoqModuleResolver
from coq_dpdgraph import dpd_to_dot, run_coq_dpdgraph
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Dependencies:
    in_the_file: set[str]
    # file name --> signature names
    in_other_files: dict[str, set[str]]
    # Does include the signature itself.
    lines_until_here_in_file: str


CLASS_RE = re.compile(r'(?m)^[ \t]*([A-Za-z_]\w*)[ \t]*:')

# def move(src: Path, dst: Path):
#     dst.parent.mkdir(parents=True, exist_ok=True)
#     shutil.move(str(src), str(dst))


# def copy(src: Path, dst: Path):
#     dst.parent.mkdir(parents=True, exist_ok=True)
#     shutil.copy(str(src), str(dst))


def rm(p: Path):
    if p.exists():
        if p.is_dir():
            p.rmdir()
        elif p.is_file():
            p.unlink()


# _: qualids
def reconstruct_line(name: str, sig_or_src: str, body: str, _: set[str], notation: str) -> str:
    """Reconstruct the complete source of the line."""
    if name:
        sig = sig_or_src
        if body:
            # We previously already added sig when body was None
            # in the main for loop
            return body  # sig + '\n' + body
        return sig
    elif notation:
        return notation
    else:
        src = sig_or_src
        return src


def a_is_outside_b(a: Path, b: Path) -> bool:
    a = a.resolve(strict=False)
    b = b.resolve(strict=False)
    try:
        a.relative_to(b)
        return False
    except ValueError:
        return True


def path_to_str_fmt(relative_path: Path) -> str:
    relative_path_str = str(relative_path)
    # If it's .. ==> OK
    # If it's SomeLocation/Etc/... ==> we want ./SomeLocation/Etc
    if not relative_path_str.startswith('.'):
        relative_path_str = './' + relative_path_str
    return relative_path_str


# The following are not included in the dependency graph:
# Require
# Require Import
# Module
# Set warnings
# Ltac
# Tactic Notation
# Hint
# Hint Rewrite
# Section

# Name + body is returned in separate runs from iter_sentences.
def build_shallow_dependencies(path_to_project_dir: Path, info_prints: bool = True):
    """
    Builds all dependencies and returns relavant information
    (such as the file dependency graph, signature dependencies for each,
    imports, etc).
    """
    if path_to_project_dir.is_file() and path_to_project_dir.name == '_CoqProject':
        path_to_project_dir = path_to_project_dir.parent

    coq_project_path = path_to_project_dir / '_CoqProject'
    coq_project_dir = coq_project_path.parent

    coqdep_dotfile = run_coqdep(coq_project_path)
    file_dependency_graph = coq_files_graph_from_dotfile(coqdep_dotfile)

    rm(coqdep_dotfile)

    files = file_dependency_graph.dependency_ordering(reverse=True)

    sercomp_args = parse_coq_project_file(coq_project_path, 'sercomp')
    coqtop_args = parse_coq_project_file(coq_project_path, 'coqtop')
    # qmap = _qmap_from_coqc_opts(coqtop_args, coq_project_path.parent)

    files_to_notations: dict[str, list[str]] = defaultdict(list)
    relative_files_to_signatures_to_dependencies: dict[str, dict[str, Dependencies]] = defaultdict(
        dict)
    files_to_sig_graphs: dict[str, CoqGraph] = defaultdict(CoqGraph)
    files_to_sig_names_to_signatures: dict[str,
                                           dict[str, str]] = defaultdict(dict)
    files_to_sig_names_to_bodies: dict[str, dict[str, str]] = defaultdict(dict)

    files_to_sig_names_to_nondot_qualids: dict[str,
                                               dict[str, set[str]]] = defaultdict(dict)
    files_to_import_watches: dict[str, set[str]] = defaultdict(set)
    files_to_exports: dict[str, set[str]] = defaultdict(set)
    files_to_instances_to_class_names: dict[str,
                                            dict[str, set[str]]] = defaultdict(dict)
    module_export_remappings: dict[str, str] = defaultdict(str)

    module_resolver = CoqModuleResolver(
        sercomp_args, coqtop_args, coq_project_dir)

    total_toplevel_sigs = 0
    total_toplevel_bodies = 0
    # We can guarrantee that this ordering of the files are correct,
    # except for imports from the other (out-of-project) libraries.
    for file in files:
        if info_prints:
            print(f"Processing file: {file}")
        relative_file_path = Path(file)

        # Now, file is relative to coq_project_dir
        # If outside of the project, skip it.
        if not (coq_project_dir / file).is_relative_to(coq_project_dir):
            continue

        dpd = run_coq_dpdgraph(
            coqtop_args,
            coq_project_path,
            relative_file_path
        )

        # If dpd file is empty, that's OK. It just has no theorems/sigs/etc.:
        if not dpd.read_text():
            # No dependencies (at least, as generated by coqdpdgraph) for file
            rm(dpd)
        else:
            dot = dpd_to_dot(dpd)
            rm(dpd)
            sig_dep_graph = coq_signature_graph_from_dotfile(dot)
            files_to_sig_graphs[file] = sig_dep_graph
            rm(dot)

        # sig_deps = sig_dep_graph.dependency_ordering()
        file_sig_deps = relative_files_to_signatures_to_dependencies[file]
        # signature name --> body
        sig_names_to_signatures = files_to_sig_names_to_signatures[file]
        sig_names_to_bodies = files_to_sig_names_to_bodies[file]
        file_instances = files_to_instances_to_class_names[file]

        line = ''
        total_signatures = 0
        total_bodies = 0
        # Trackers for Require Import. Look inside the for loop to see why this is needed.
        watch_for = files_to_import_watches[file]
        # Example: If we have 'Require Data.Tuple.', we keep track of
        # the fact that Tuple.xxx ==> Data.Tuple.xxx.
        # Applies to 'Require Import' as well.
        require_watches: dict[str, str] = defaultdict(str)
        # a `qualid` stands for 'qualified identifier'
        # known_qualids_to_file_paths: dict[str, str] = defaultdict(str)
        for name, sig_or_src, body, qualids, notation in iter_sentences(sercomp_args, coq_project_path, relative_file_path):
            signature_exists = name != ''
            body_exists = body != ''
            if notation:
                files_to_notations[file].append(notation)
            if signature_exists:
                # We also add instances:
                if sig_or_src.startswith('Class ') or sig_or_src.startswith('Instance '):
                    for field_instance in CLASS_RE.findall(sig_or_src):
                        if field_instance not in file_instances:
                            file_instances[field_instance] = set()
                        # The field instance could correspond to <any> of the classes in file.
                        # (that's why it's a set).
                        file_instances[field_instance].add(name)

                if name not in file_sig_deps:
                    file_sig_deps[name] = Dependencies(
                        set(), defaultdict(set), '')

                sig_names_to_signatures[name] = sig_or_src
                total_signatures += 1
                if body_exists:
                    total_bodies += 1
                    sig_names_to_bodies[name] = body
            else:
                # If modifying
                # DO NOT use continue here. Otherwise lines will NOT be collected correctly!!
                # Signature does not exist
                src = sig_or_src
                # Another issue: Coqdpdgraph does not properly resolve all dependencies
                # when used with 'Require Import'. As an example, take a look at
                # hs-to-coq/base-thy/GHC/Enum.v. eftInt_aux_rhs depends on eftInt_aux_pf,
                # which is defined in hs-to-coq/base/GHC/Enum.v, imported via
                # 'Require Import GHC.Enum'. But eftInt_aux_pf is not displayed
                # as a dependency of eftInt_aux_rhs.
                imported_modules = []
                if src.startswith('Require Import'):
                    # If split()[2] does not exist; syntax error.
                    require_import = src.split()[2]
                    imported_modules.append(require_import)

                    # Data.Tuple. ==> last_ident = Tuple
                    # -2 because last identifier is the dot,
                    # [-1] would always be ''.
                    split = require_import.split('.')
                    if not (len(split) < 2 or split[0] == 'Coq'):
                        last_ident = split[-2]
                        require_watches[last_ident] = require_import
                elif len(src.split()) >= 4 and src.split()[0] == 'From' and src.split()[2] == 'Import':
                    parts = src.split()
                    # From Data.Tuple Require Import Tuple.fst, Hello.snd.
                    # So, the imported modules are: Data.Tuple.Tuple.fst, Data.Tuple.Hello.snd
                    # We have to concatenate the first part
                    # For performance: You could directly track the last prefix - i.e
                    # snd - but that's not worth the code changes. They'll be automatically
                    # found by transitivity.
                    base_prefix = parts[1]
                    modules = [m.rstrip(',') for m in parts[3:]]
                    imported_modules.extend(
                        f"{base_prefix}.{mod}" for mod in modules)
                elif src.startswith('Require Export'):
                    # Then this is quite like 'Require Import', but whatever
                    # includes the current file also includes the exporteed files here.
                    # So, any file including the current file, also by transitivity,
                    # includes the require exported files.
                    exported_module = src.split()[2]

                    relative_export_path = module_resolver.coq_module_to_path(
                        exported_module,
                        extern_maps=module_export_remappings
                    )

                    exported_last_id = exported_module.split('.')[-2] + '.'
                    module_export_remappings[exported_last_id] = exported_module

                    if relative_export_path and (coq_project_dir / relative_export_path).exists():
                        # the module also depends on the modules it exports.
                        # The transitivity is handled after in final
                        # for loop.
                        imported_modules.append(exported_module)

                        files_to_exports[file].add(
                            path_to_str_fmt(relative_export_path)
                        )
                elif len(src.split()) >= 4 and src.split()[0] == 'From' and src.split()[2] == 'Export':
                    print(f"Warning: FROM EXPORT: {src}. Skipping.")
                    # Same as the above branch, with a different index.
                    # ie From Data.Tuple Export Tuple.fst, Hello.snd.
                    # exported_module = src.split()[1]
                elif len(src.split()) >= 5 and src.startswith('From') and src.split()[2] == 'Require' and src.split()[3] == 'Import':
                    print(f"Warning: FROM REQUIRE IMPORT: {src}. Skipping.")
                    # This occurence does not happen in the projects ^ or when it does, it occurs with standart libraries
                    # From AAA Require Import YYY
                elif src.startswith('Require'):
                    if len(src.split()) == 2:
                        require_import = src.split()[1]
                        # Data.Tuple. ==> last_ident = Tuple
                        # -2 because last identifier is the dot,
                        # [-1] would always be ''.
                        split = require_import.split('.')
                        if not (len(split) < 2 or split[0] == 'Coq'):
                            last_ident = split[-2]
                            require_watches[last_ident] = require_import

                for imported_module in imported_modules:
                    relative_dep_path = module_resolver.coq_module_to_path(
                        imported_module,
                        extern_maps=module_export_remappings
                    )

                    # Now we have the relative path to the imported module.
                    # We can figure out its signatures, check if anything matches,
                    # and add to the dependencies.
                    if relative_dep_path and (coq_project_dir / relative_dep_path).exists():
                        if '.opam' not in relative_dep_path.parts or 'user-contrib' in relative_dep_path.parts:
                            watch_for.add(path_to_str_fmt(relative_dep_path))
                        # file_dependency_graph.add_edge(
                        #     str(relative_dep_path),
                        #     file
                        # )

                    # Else, it's a Coq or any other standard library import, not
                    # project based.

            # What's going on here with iterating over imports such as MyModule.InnerModule.theorem
            # for each function?
            # The 'signature graph' we have o/--nly gives us the dependencies in the file itself,
            # which can sometimes miss dependencies in other files. So, this section iterates
            # over all the imports, and for each import, adds the dependencies (all dependencies)
            # to the file_deps for the current file.
            # if file == './Data/Tuple.v' :
            #     print('qualids:', qualids)

            for qualid in qualids:
                # locate_qualid(qualid, line, coq_project_dir, sercomp_args)
                if '.' not in qualid:
                    if not signature_exists:
                        continue

                    names_to_qualids = files_to_sig_names_to_nondot_qualids[file]
                    if name not in names_to_qualids:
                        names_to_qualids[name] = set()

                    names_to_qualids[name].add(qualid)
                    continue

                sig_name = qualid.split('.')[-1]
                initial_prefix = qualid.split('.')[0]

                # print(f'Initial qualid={qualid}, initial_prefix={initial_prefix}, sig_name={sig_name}')

                # The import could be mapped by 'Require' or 'Require Import' directly.
                # Require Data.Tuple. ==> if used with Tuple.fst, then we want
                # to map Tuple.fst back to Data.Tuple.fst.
                if initial_prefix in require_watches:
                    # qualids: {'Tuple.fst', 'B', 'fst', 'A'}
                    # Consider Tuple.fst. Our require watches will have
                    # Tuple ==> mapping to Data.Tuple. (with a dot)
                    # We want to transfrom the qualid to Data.Tuple.fst.
                    qualid = require_watches[initial_prefix] + sig_name

                relative_dep_path = module_resolver.coq_module_to_path(
                    qualid,
                    extern_maps=module_export_remappings
                )
                if not relative_dep_path:
                    # Either not resolved, or a standard library import.
                    continue

                if '.opam' in relative_dep_path.parts and 'user-contrib' not in relative_dep_path.parts:
                    continue
                # print('Resolved:', qualid, 'to', relative_dep_path)

                # first_ident = relative_dep_path.parts[-1].split('.')[0]

                # sig_name = qualid.split('.')[-1]
                # relative_dep_path = module_resolver.coq_module_to_path(qualid)
                # if not relative_dep_path:
                #     # Either not resolved, or a standard library import.
                #     continue
                # print('Resovlved:', qualid, 'to', relative_dep_path)

                # # The import could be mapped by 'Require' directly.
                # # Require Data.Tuple. ==> if used with Tuple.fst, then we want
                # # to map Tuple.fst back to Data.Tuple.fst.
                # first_ident = relative_dep_path.parts[-1].split('.')[0]
                # if first_ident in require_watches:
                #     # qualids: {'Tuple.fst', 'B', 'fst', 'A'}
                #     # Consider Tuple.fst. Our require watches will have
                #     # Tuple ==> mapping to Data.Tuple. (with a dot)
                #     # We want to transfrom the qualid to Data.Tuple.fst.
                #     qualid = require_watches[first_ident] + sig_name
                # if debug_flag:
                #     print('qualid:', qualid)

                # If they are the same file? This edge case should not happen,
                # but better to cover it:

                if relative_dep_path == relative_file_path:
                    # self-import?
                    continue

                if (coq_project_dir / relative_dep_path).exists():
                    # file_dependency_graph.add_edge(
                    #     str(relative_dep_path),
                    #     file
                    # )

                    if not signature_exists:
                        # caused by imports, there's a qualid but no signature
                        continue

                    file_sig_deps[name].in_other_files[str(
                        path_to_str_fmt(relative_dep_path)
                    )].add(sig_name)

            if signature_exists and body_exists:
                # if debug_flag:
                #     print(f"Adding body: {name} in {file}, line\n==\n{line}\n==")
                file_sig_deps[name].lines_until_here_in_file = line

            line += reconstruct_line(
                name,
                sig_or_src,
                body,
                qualids,
                notation
            ) + '\n'

        # Here we add the dependencies of the signatures in the SAME file
        sig_names_keys = sig_names_to_signatures.keys()
        for sig_name in sig_names_keys:
            sig_deps_in_file = sig_dep_graph.dependencies_of(sig_name)
            file_sig_deps[sig_name].in_the_file.update(sig_deps_in_file)

        if info_prints:
            print(f"{total_signatures} top-level signatures collected for {file}")
            print(f"{total_bodies} top-level proof bodies collected for {file}\n")

        total_toplevel_sigs += total_signatures
        total_toplevel_bodies += total_bodies

    if info_prints:
        # Signatures include proof count as well, so if you want
        # the count of definitions only you must subtract the two.
        print(f"\nTotal signatures collected: {total_toplevel_sigs}\n")
        print(f"Total proofs collected: {total_toplevel_bodies}\n")

    # Must resolve/'propagate' exports and follow them.
    # If C imports B and B exports A, then C should also watch A
    for file in file_dependency_graph.dependency_ordering(reverse=True):
        for dep_file in file_dependency_graph.dependencies_of(file):
            if dep_file in files_to_exports:
                exports = files_to_exports[dep_file]
                # File depends on dep_file. Dep_file exports 'exports'.
                # Now, File must also watch for these exports.
                files_to_import_watches[file].update(exports)

    # Resolve each file's Require Import / From ... Import, dependencies.
    # A cleaner way to do this is to call SerApi + Locate, but this
    # takes a longer time for larger projects.
    for file in file_dependency_graph.dependency_ordering(reverse=True):
        file_deps = relative_files_to_signatures_to_dependencies[file]
        import_watches = files_to_import_watches[file]
        nondot_qualids = files_to_sig_names_to_nondot_qualids[file]
        for signature_name in nondot_qualids:
            qualids_for_sig = nondot_qualids[signature_name]
            for watched_file in import_watches:
                file_signatures = files_to_sig_names_to_signatures[watched_file]
                for qualid in qualids_for_sig:
                    if qualid in file_signatures:
                        file_deps[signature_name].in_other_files[watched_file].add(
                            qualid)

            # Also resolve class instances:
            for watched_file in import_watches:
                if watched_file in files_to_instances_to_class_names:
                    file_instance_names = files_to_instances_to_class_names[watched_file]
                    for qualid in qualids_for_sig:
                        if qualid in file_instance_names:
                            classes_for_qualid = file_instance_names[qualid]
                            for class_name in classes_for_qualid:
                                file_deps[signature_name].in_other_files[watched_file].add(
                                    class_name
                                )

    # ASSERTIONS (never happened during the experiment object collection)
    # If you're modifying, uncomment to check for another project other than
    # verdi or hs-to-coq/base-thy.
    #
    # for file in file_dependency_graph.dependency_ordering(reverse=True):
    #     for sig_name in relative_files_to_signatures_to_dependencies[file]:
    #         deps = relative_files_to_signatures_to_dependencies[file][sig_name]
    #         for other_file in deps.in_other_files:
    #             if other_file not in files_set:
    #                 # assert
    #                 print(other_file, 'not in', files_set)
    #                 from sys import exit
    #                 exit(0)
        

    return (
        file_dependency_graph,
        relative_files_to_signatures_to_dependencies,
        files_to_sig_graphs,
        files_to_sig_names_to_bodies,
        files_to_sig_names_to_signatures,
        files_to_notations,
    )
