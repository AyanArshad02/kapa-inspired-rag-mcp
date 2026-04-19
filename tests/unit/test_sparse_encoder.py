import pytest

from backend.strategies.embedding.tf_sparse_encoder import TFSparseEncoder


class TestTFSparseEncoder:
    def setup_method(self):
        self.encoder = TFSparseEncoder(top_k=64)

    async def test_returns_one_pair_per_input(self):
        texts = ["hello world", "install kubernetes", "configure the cluster"]
        results = await self.encoder.encode(texts)
        assert len(results) == 3

    async def test_indices_and_values_same_length(self):
        results = await self.encoder.encode(["some text here"])
        indices, values = results[0]
        assert len(indices) == len(values)

    async def test_all_values_positive(self):
        results = await self.encoder.encode(["some text here with multiple words"])
        _, values = results[0]
        assert all(v > 0 for v in values)

    async def test_empty_string_returns_empty_pair(self):
        results = await self.encoder.encode([""])
        indices, values = results[0]
        assert indices == []
        assert values == []

    async def test_repeated_token_gets_higher_weight_than_rare(self):
        # "install" repeated many times vs "kubernetes" once
        text = "install install install install install kubernetes"
        results = await self.encoder.encode([text])
        indices, values = results[0]

        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        install_id = enc.encode(" install")[0]
        kubernetes_id = enc.encode(" kubernetes")[0]

        weight_map = dict(zip(indices, values))
        assert weight_map[install_id] > weight_map[kubernetes_id]

    async def test_top_k_limits_output_size(self):
        encoder = TFSparseEncoder(top_k=10)
        long_text = " ".join([f"word{i}" for i in range(200)])
        results = await encoder.encode([long_text])
        indices, values = results[0]
        assert len(indices) <= 10

    async def test_indices_are_integers(self):
        results = await self.encoder.encode(["test content"])
        indices, _ = results[0]
        assert all(isinstance(i, int) for i in indices)

    async def test_same_text_produces_same_output(self):
        text = ["deterministic output test"]
        r1 = await self.encoder.encode(text)
        r2 = await self.encoder.encode(text)
        assert r1[0][0] == r2[0][0]
        assert r1[0][1] == r2[0][1]
