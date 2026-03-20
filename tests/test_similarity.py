"""Similarity and routing accuracy tests for the Glyphh Code model."""

import pytest
from glyphh import Encoder
from glyphh.core.types import Concept
from glyphh.core.ops import cosine_similarity

from encoder import ENCODER_CONFIG, encode_query


@pytest.fixture
def encoder():
    return Encoder(ENCODER_CONFIG)


def _encode_file(encoder, path_tokens, identifiers, imports=""):
    """Helper to encode a file record as a glyph."""
    return encoder.encode(Concept(
        name=path_tokens.replace(" ", "/"),
        attributes={
            "path_tokens": path_tokens,
            "identifiers": identifiers,
            "imports": imports,
        },
    ))


def _encode_query(encoder, query):
    """Helper to encode a NL query as a glyph."""
    result = encode_query(query)
    return encoder.encode(Concept(
        name=result["name"],
        attributes=result["attributes"],
    ))


class TestSimilarityBasics:
    """Basic similarity properties."""

    def test_identical_files_perfect_similarity(self, encoder):
        g1 = _encode_file(encoder, "src services auth py", "auth token validate jwt hash")
        g2 = _encode_file(encoder, "src services auth py", "auth token validate jwt hash")
        sim = cosine_similarity(g1.global_cortex.data, g2.global_cortex.data)
        assert sim == 1.0

    def test_different_files_lower_than_related(self, encoder):
        """Unrelated files should score lower than related ones."""
        auth = _encode_file(encoder, "src services auth py", "auth token validate jwt hash")
        css = _encode_file(encoder, "lib css theme scss", "color font margin padding border")
        test_auth = _encode_file(encoder, "tests test auth py", "test auth token validate mock")

        sim_unrelated = cosine_similarity(auth.global_cortex.data, css.global_cortex.data)
        sim_related = cosine_similarity(auth.global_cortex.data, test_auth.global_cortex.data)
        assert sim_related > sim_unrelated

    def test_related_files_moderate_similarity(self, encoder):
        g1 = _encode_file(
            encoder,
            "src services user service py",
            "user create delete update email password",
            "sqlalchemy fastapi",
        )
        g2 = _encode_file(
            encoder,
            "tests test user service py",
            "test create user test delete user mock fixture",
            "pytest mock services user",
        )
        sim = cosine_similarity(g1.global_cortex.data, g2.global_cortex.data)
        assert 0.20 < sim < 0.80  # Related but not identical


class TestQueryRouting:
    """Test that NL queries route to the correct files."""

    @pytest.fixture
    def file_glyphs(self, encoder):
        """Create a small catalog of file glyphs with rich vocabularies.

        At 2000 dims, BoW needs enough distinctive tokens to discriminate.
        Real files have hundreds of tokens — these test exemplars use 20+.
        """
        files = {
            "auth_service": _encode_file(
                encoder,
                "src services auth service py",
                (
                    "auth authenticate login logout token jwt refresh password "
                    "hash verify bearer middleware session cookie expire claims "
                    "issuer audience decode encode secret bcrypt rounds salt"
                ),
                "bcrypt pyjwt fastapi sqlalchemy passlib",
            ),
            "payment_handler": _encode_file(
                encoder,
                "src handlers payment py",
                (
                    "payment charge refund stripe subscription invoice webhook "
                    "billing amount currency customer card declined receipt "
                    "checkout session intent capture payout transfer balance"
                ),
                "stripe httpx aiohttp",
            ),
            "database_migration": _encode_file(
                encoder,
                "migrations versions add users table py",
                (
                    "alembic migration upgrade downgrade revision autogenerate "
                    "schema alter add column drop index foreign constraint "
                    "batch operations metadata naming convention"
                ),
                "alembic sqlalchemy",
            ),
            "react_component": _encode_file(
                encoder,
                "src components dashboard tsx",
                (
                    "react component dashboard widget chart graph render "
                    "useState useEffect props children jsx tsx onclick "
                    "className tailwind grid flex responsive layout"
                ),
                "react recharts tailwindcss",
            ),
        }
        return files

    def _best_match(self, encoder, query, file_glyphs):
        """Find the best matching file for a query."""
        q = _encode_query(encoder, query)
        scores = {
            name: cosine_similarity(q.global_cortex.data, g.global_cortex.data)
            for name, g in file_glyphs.items()
        }
        return max(scores, key=scores.get), scores

    def test_auth_query_matches_auth_service(self, encoder, file_glyphs):
        best, scores = self._best_match(
            encoder, "jwt token authenticate bearer login password", file_glyphs
        )
        assert best == "auth_service", f"Expected auth_service, got {best}: {scores}"

    def test_payment_query_matches_payment_handler(self, encoder, file_glyphs):
        best, scores = self._best_match(
            encoder, "stripe charge refund billing invoice", file_glyphs
        )
        assert best == "payment_handler", f"Expected payment_handler, got {best}: {scores}"

    def test_database_query_matches_migration(self, encoder, file_glyphs):
        best, scores = self._best_match(
            encoder, "alembic migration upgrade downgrade schema", file_glyphs
        )
        assert best == "database_migration", f"Expected database_migration, got {best}: {scores}"

    def test_react_query_matches_component(self, encoder, file_glyphs):
        best, scores = self._best_match(
            encoder, "react component dashboard widget chart jsx", file_glyphs
        )
        assert best == "react_component", f"Expected react_component, got {best}: {scores}"


class TestLayerSimilarity:
    """Test that path and content layers contribute independently."""

    def test_same_path_different_content(self, encoder):
        """Files at same path but different content: path layer high, content layer lower."""
        g1 = _encode_file(
            encoder, "src utils helpers py",
            "parse json format date serialize deserialize stringify",
            "json datetime",
        )
        g2 = _encode_file(
            encoder, "src utils helpers py",
            "encrypt decrypt hash verify signature certificate openssl",
            "cryptography hashlib",
        )
        path_sim = cosine_similarity(
            g1.layers["path"].cortex.data,
            g2.layers["path"].cortex.data,
        )
        content_sim = cosine_similarity(
            g1.layers["content"].cortex.data,
            g2.layers["content"].cortex.data,
        )
        assert path_sim > 0.90  # Same path
        assert content_sim < path_sim  # Content should differ more than path

    def test_different_path_same_content(self, encoder):
        """Files with same content but different paths."""
        g1 = _encode_file(encoder, "src services auth py", "auth token validate jwt")
        g2 = _encode_file(encoder, "lib middleware verify py", "auth token validate jwt")
        path_sim = cosine_similarity(
            g1.layers["path"].cortex.data,
            g2.layers["path"].cortex.data,
        )
        content_sim = cosine_similarity(
            g1.layers["content"].cortex.data,
            g2.layers["content"].cortex.data,
        )
        assert path_sim < 0.50  # Different paths
        assert content_sim > 0.90  # Same content


class TestImportSignal:
    """Test that imports provide meaningful signal."""

    def test_shared_imports_increase_similarity(self, encoder):
        """Files sharing imports should be more similar than those with no overlap."""
        g_shared = _encode_file(
            encoder, "src a py", "foo bar",
            "sqlalchemy fastapi pydantic",
        )
        g_also_shared = _encode_file(
            encoder, "src b py", "baz qux",
            "sqlalchemy fastapi httpx",
        )
        g_different = _encode_file(
            encoder, "src c py", "baz qux",
            "react nextjs tailwind",
        )

        sim_shared = cosine_similarity(
            g_shared.global_cortex.data,
            g_also_shared.global_cortex.data,
        )
        sim_different = cosine_similarity(
            g_shared.global_cortex.data,
            g_different.global_cortex.data,
        )
        assert sim_shared > sim_different


class TestMCPToolSchemas:
    """Validate MCP tool definitions."""

    def test_mcp_tools_defined(self):
        from encoder import MCP_TOOLS
        assert isinstance(MCP_TOOLS, list)
        assert len(MCP_TOOLS) >= 2

    def test_search_tool_schema(self):
        from encoder import MCP_TOOLS
        search = next(t for t in MCP_TOOLS if t["name"] == "glyphh_search")
        assert "description" in search
        assert search["input_schema"]["required"] == ["query"]

    def test_related_tool_schema(self):
        from encoder import MCP_TOOLS
        related = next(t for t in MCP_TOOLS if t["name"] == "glyphh_related")
        assert related["input_schema"]["required"] == ["file_path"]

    def test_handle_mcp_tool_defined(self):
        from encoder import handle_mcp_tool
        import asyncio
        assert asyncio.iscoroutinefunction(handle_mcp_tool)
