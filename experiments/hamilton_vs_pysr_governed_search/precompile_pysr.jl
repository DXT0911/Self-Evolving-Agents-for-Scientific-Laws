using Pkg

println("stage=instantiate")
flush(stdout)
Pkg.instantiate()

println("stage=precompile")
flush(stdout)
Pkg.precompile()

println("stage=load_symbolic_regression")
flush(stdout)
using SymbolicRegression

println("stage=ready julia=", VERSION)
flush(stdout)
