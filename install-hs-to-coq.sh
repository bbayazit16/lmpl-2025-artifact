opam switch coq-8.10.2
eval $(opam env)

command -v coqc >/dev/null 2>&1 || { echo >&2 "coqc not found"; exit 1; }

cd /evaluation
git clone https://github.com/antalsz/hs-to-coq.git
cd hs-to-coq
git checkout cd62a35fff22cb6022a8935581746df658264f0f
stack setup
stack build

make -C base
make -C base-thy
