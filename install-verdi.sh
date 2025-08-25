cd /evaluation

opam switch coq-8.11.0
eval $(opam env)

git clone https://github.com/uwplse/cheerios
cd cheerios
git checkout 9c7f66e57b91f706d70afa8ed99d64ed98ab367d
./configure
make
make install
cd ..

git clone https://github.com/uwplse/verdi
cd verdi
git checkout fdb4ede19d2150c254f0ebcfbed4fb9547a734b0
./configure
make
make install
