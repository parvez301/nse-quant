"""Minimal `scipy.sparse` stub so we can load `lightgbm` without the real
113 MB scipy dependency.

lightgbm.basic does `import scipy.sparse` at module load and uses the symbols
only inside `isinstance(data, scipy.sparse.csr_matrix)` checks. Our handler
always passes dense numpy arrays, so those checks always return False — the
sparse code path is never executed. This stub satisfies the import contract
without pulling in scipy itself.
"""
import sys
import types


def install():
    if "scipy.sparse" in sys.modules:
        return
    scipy = types.ModuleType("scipy")
    sparse = types.ModuleType("scipy.sparse")

    # Empty sentinel classes — only used by lightgbm in isinstance() checks.
    # We will never construct or pass instances of these.
    class _Sentinel:
        pass

    for name in ("spmatrix", "csr_matrix", "csc_matrix",
                 "coo_matrix", "csr_array", "csc_array"):
        setattr(sparse, name, type(name, (_Sentinel,), {}))

    scipy.sparse = sparse
    sys.modules["scipy"] = scipy
    sys.modules["scipy.sparse"] = sparse
