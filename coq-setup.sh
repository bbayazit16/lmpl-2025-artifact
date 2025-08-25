opam init -y --disable-sandboxing

opam switch create coq-8.10.2 ocaml-base-compiler.4.07.1 \
 && eval "$(opam env --switch=coq-8.10.2)" \
 && opam repo add coq-released https://coq.inria.fr/opam/released \
 && opam update \
 && opam install -y coq.8.10.2 coq-mathcomp-ssreflect.1.10.0 coq-serapi coq-dpdgraph.0.6.6

opam switch create coq-8.11.0 ocaml-variants.4.08.1+flambda \
 && eval "$(opam env --switch=coq-8.11.0)" \
 && opam repo add coq-released https://coq.inria.fr/opam/released \
 && opam repo add coq-extra-dev https://coq.inria.fr/opam/extra-dev \
 && opam install -y coq.8.11.0 coq-serapi coq-dpdgraph coq-struct-tact coq-inf-seq-ext coq-dpdgraph.0.6.7