from collections import deque
import pydot
from pathlib import Path
from typing import Literal, Optional

# From the README file: https://github.com/rocq-community/coq-dpdgraph
# green : proved lemma
# orange : axiom/admitted lemma
# dark pink : Definition, etc
# light pink : Parameter, etc
# violet : inductive,
# blue : constructor,
# multi-circled : not used (no predecessor in the graph)
# yellow box : module

# https://github.com/rocq-community/coq-dpdgraph/blob/7817def06d4e3abc2e54a2600cf6e29d63d58b8a/dpd_dot.ml#L15
# color_soft_yellow = "#FFFFC3"

# color_pale_orange = "#FFE1C3"
# color_medium_orange = "#FFB57F"

# color_soft_green = "#7FFFD4"
# color_medium_green = "#00E598"

# color_soft_pink = "#FACDEF"
# color_medium_pink = "#F070D1"

# color_soft_purple = "#E2CDFA"
# color_soft_blue = "#7FAAFF"

DOT_KEYWORDS = ['node', 'edge', 'graph']
DOT_ATTRS = ['label', 'color', 'fillcolor', 'shape', 'style']


class CoqGraph:
    # node_id -> node attributes
    nodes: dict[str, dict]
    # (source, target)
    edges: list[tuple[str, str]]
    # node_id --> target nodes
    adjacency_list: dict[str, set[str]]
    # node_id --> source nodes
    reverse_adjacency_list: dict[str, set[str]]

    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.adjacency_list = {}
        self.reverse_adjacency_list = {}

    def add_node(self, node_id: str, attributes: Optional[dict] = None):
        """Add a node to the graph"""
        self.nodes[node_id] = attributes or dict()
        if node_id not in self.adjacency_list:
            self.adjacency_list[node_id] = set()
        if node_id not in self.reverse_adjacency_list:
            self.reverse_adjacency_list[node_id] = set()

    def add_edge(self, source: str, target: str):
        """Add an edge, source --> target"""
        if source not in self.nodes:
            self.add_node(source)
        if target not in self.nodes:
            self.add_node(target)

        self.edges.append((source, target))
        self.adjacency_list[source].add(target)
        self.reverse_adjacency_list[target].add(source)

    def dependency_ordering(self, reverse: bool = False) -> list[str]:
        """
        Order by theorem/file dependencies (topological sort).
        """
        in_degree = {
            node: len(self.reverse_adjacency_list[node]) for node in self.nodes}

        queue = deque(
            [node for node, degree in in_degree.items() if degree == 0])
        result: list[str] = []

        while queue:
            current = queue.popleft()
            result.append(current)

            for neighbor in self.adjacency_list[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self.nodes):
            raise ValueError('Invalid graph')

        return list(result) if not reverse else list(reversed(result))

    def would_create_cycle(self, source: str, target: str) -> bool:
        """Return true if adding the edge would create a cycle"""
        if source == target:
            return True

        visited = set()
        queue = deque([target])

        while queue:
            current = queue.popleft()
            if current == source:
                return True

            visited.add(current)
            for neighbor in self.adjacency_list.get(current, set()):
                if neighbor not in visited:
                    queue.append(neighbor)

        return False

    def dependencies_of(self, name) -> set[str]:
        """
        Return a maping signature names --> their dependencies, including the
        transitive dependencies (so recursively follows and retrieves all dependencies).
        The return value does not include the name itself.
        """
        if name not in self.nodes:
            return set()

        dependencies = set()
        queue = deque([name])

        while queue:
            current = queue.popleft()
            for neighbor in self.adjacency_list[current]:
                if neighbor not in dependencies and neighbor != name:
                    dependencies.add(neighbor)
                    queue.append(neighbor)

        return dependencies

def coq_signature_graph_from_dotfile(dotfile: Path) -> CoqGraph:
    """Parse a DOT file and return a graph of Coq theorems."""
    if not dotfile.exists():
        raise FileNotFoundError(f"DOT file not found: {dotfile}")

    graphs = pydot.graph_from_dot_file(str(dotfile))
    if not graphs:
        raise ValueError(f"Could not parse DOT file: {dotfile}")

    if len(graphs) > 1:
        print('more than one graph - handle this case?? using graphs[0]')

    dot_graph = graphs[0]
    coq_graph = CoqGraph()

    node_id_to_label = {}

    for node in dot_graph.get_nodes():
        node_name = node.get_name().strip('"')
        if node_name in DOT_KEYWORDS:
            continue

        attributes = {}
        for attr_name in DOT_ATTRS:
            attr_value = node.get(attr_name)
            if attr_value:
                attributes[attr_name] = attr_value.strip('"')

        label = attributes.get('label', node_name)
        node_id_to_label[node_name] = label

        coq_graph.add_node(label, attributes)

    for edge in dot_graph.get_edges():
        source = str(edge.get_source()).strip('"')
        target = str(edge.get_destination()).strip('"')

        if source == target or source in DOT_KEYWORDS or target in DOT_KEYWORDS:
            continue

        source_label = node_id_to_label.get(source, source)
        target_label = node_id_to_label.get(target, target)

        if source_label == target_label:
            continue

        if not coq_graph.would_create_cycle(source_label, target_label):
            coq_graph.add_edge(source_label, target_label)
        else:
            print('Warning, label conflict:', source, '-->', target_label)

    return coq_graph


def coq_files_graph_from_dotfile(dotfile: Path) -> CoqGraph:
    """
    Parse a DOT file and return a graph of Coq file dependencies.
    Adds full path of files to the node edges.
    """
    if not dotfile.exists():
        raise FileNotFoundError(f"DOT file not found: {dotfile}")

    graphs = pydot.graph_from_dot_file(str(dotfile))
    if not graphs:
        raise ValueError(f"Could not parse DOT file: {dotfile}")

    if len(graphs) > 1:
        import sys
        sys.exit('more than one graphs handle this case??')

    dot_graph = graphs[0]
    coq_graph = CoqGraph()

    for node in dot_graph.get_nodes():
        node_name = node.get_name().strip('"')
        if node_name in DOT_KEYWORDS:
            continue

        attributes = {}
        for attr_name in DOT_ATTRS:
            attr_value = node.get(attr_name)
            if attr_value:
                attributes[attr_name] = attr_value.strip('"')

        if not node_name.endswith('.v'):
            node_name += '.v'

        coq_graph.add_node(node_name, attributes)

    for edge in dot_graph.get_edges():
        source = str(edge.get_source()).strip('"')
        target = str(edge.get_destination()).strip('"')

        if source == target or source in DOT_KEYWORDS or target in DOT_KEYWORDS:
            continue

        if not source.endswith('.v'):
            source += '.v'
        if not target.endswith('.v'):
            target += '.v'

        # If it's .. ==> OK
        # If it's SomeLocation/Etc/... ==> we want ./SomeLocation/Etc
        if not source.startswith('.'):
            source = './' + source
        if not target.startswith('.'):
            target = './' + target

        coq_graph.add_edge(target, source)

    return coq_graph
