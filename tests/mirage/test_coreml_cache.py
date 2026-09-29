import os

from mirage.upstream import COREML, coreml_cache_for, with_coreml_cache


def model(tmp_path, name="swap.onnx", data=b"v1"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_names_and_tuples_both_get_the_cache_folder(tmp_path):
    m, root = model(tmp_path), tmp_path / "cache"
    providers, options = with_coreml_cache(m, [COREML, "CPUExecutionProvider"],
                                           [{"MLComputeUnits": "CPUAndGPU"}, {}], root)
    assert options is None
    (name, opts), (cpu, cpu_opts) = providers
    assert name == COREML and opts["MLComputeUnits"] == "CPUAndGPU"
    assert os.path.isdir(opts["ModelCacheDirectory"]) and cpu == "CPUExecutionProvider" and cpu_opts == {}
    providers, _ = with_coreml_cache(m, [(COREML, {"ModelFormat": "MLProgram"})], None, root)
    assert providers[0][1]["ModelCacheDirectory"] == opts["ModelCacheDirectory"]


def test_cpu_only_sessions_are_left_alone(tmp_path):
    m = model(tmp_path)
    assert with_coreml_cache(m, ["CPUExecutionProvider"], None, tmp_path / "c") == (["CPUExecutionProvider"], None)
    assert with_coreml_cache(m, None, None, tmp_path / "c") == (None, None)
    assert not (tmp_path / "c").exists()


def test_an_explicit_cache_folder_wins(tmp_path):
    m = model(tmp_path)
    given = [(COREML, {"ModelCacheDirectory": "/somewhere"})]
    assert with_coreml_cache(m, given, None, tmp_path / "c") == (given, None)


def test_a_replaced_model_gets_a_new_folder_and_the_old_one_goes(tmp_path):
    root = tmp_path / "cache"
    m = model(tmp_path)
    first = coreml_cache_for(m, root)
    (first / "compiled").write_text("x")
    other = coreml_cache_for(model(tmp_path, "swap.onnx.bak", b"other"), root)   # a different model stays
    m.write_bytes(b"version two")
    os.utime(m, ns=(1, 2_000_000_000))
    second = coreml_cache_for(m, root)
    assert second != first and not first.exists() and second.is_dir() and other.is_dir()


def test_a_broken_cache_falls_back_to_a_plain_load(tmp_path, monkeypatch):
    import onnxruntime as ort

    from mirage import upstream

    calls = []

    def fake_init(self, path, sess_options=None, providers=None, provider_options=None, **kw):
        calls.append(providers)
        if providers and isinstance(providers[0], tuple) and "ModelCacheDirectory" in providers[0][1]:
            raise RuntimeError("corrupt compiled model")

    monkeypatch.setattr(ort.InferenceSession, "__init__", fake_init)
    monkeypatch.setenv("MIRAGE_HOME", str(tmp_path / "home"))
    upstream._cache_compiled_coreml_models()
    ort.InferenceSession(str(model(tmp_path)), providers=[(COREML, {}), "CPUExecutionProvider"])
    assert len(calls) == 2 and calls[1] == [(COREML, {}), "CPUExecutionProvider"]
    cache_root = tmp_path / "home" / "cache" / "coreml"
    assert not any(cache_root.iterdir())   # the broken folder is gone
