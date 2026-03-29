"""Tests for session_write / session_recall HDC encoding.

Unit tests verify the session encoder produces meaningful vectors —
semantically similar notes should cluster at the content layer,
file path mentions should cluster at the context layer, and the
temporal layer should differentiate notes written at different times.
"""

import pytest
import numpy as np

from glyphh.core.ops import cosine_similarity

from glyphh_code.encoder import (
    SESSION_ENCODER_CONFIG,
    _encode_session_concept,
    _session_tokenize,
    _get_session_encoder,
    _session_score,
    _SESSION_PREFIX,
)


@pytest.fixture
def encoder():
    return _get_session_encoder()


def _encode_note(encoder, content: str, label: str = "test"):
    concept = _encode_session_concept(content, label)
    return encoder.encode(concept)


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

class TestSessionTokenize:

    def test_basic(self):
        words = _session_tokenize("Refactored the auth middleware to use JWT tokens")
        assert "auth" in words
        assert "middleware" in words
        assert "jwt" in words
        assert "tokens" in words

    def test_stop_words_filtered(self):
        words = _session_tokenize("the file is in the code and it has a function")
        assert "the" not in words
        assert "and" not in words

    def test_camelcase_split(self):
        words = _session_tokenize("GlyphStorage handles operations")
        assert "glyph" in words
        assert "storage" in words

    def test_snake_case_split(self):
        words = _session_tokenize("handle_mcp_tool dispatches calls")
        assert "handle" in words
        assert "mcp" in words
        assert "tool" in words


# ---------------------------------------------------------------------------
# Concept attributes
# ---------------------------------------------------------------------------

class TestEncodeSessionConcept:

    def test_identifiers_populated(self):
        concept = _encode_session_concept("Auth middleware validates JWT tokens", "test")
        assert "auth" in concept.attributes["identifiers"]
        assert "middleware" in concept.attributes["identifiers"]
        assert "jwt" in concept.attributes["identifiers"]

    def test_paths_extracted(self):
        concept = _encode_session_concept(
            "Changed encoder.py and compile.py to support sessions", "test"
        )
        assert "encoder" in concept.attributes["paths"]
        assert "compile" in concept.attributes["paths"]

    def test_symbols_extracted_camelcase(self):
        concept = _encode_session_concept(
            "The GlyphStorage class handles all DB operations", "test"
        )
        assert "glyph" in concept.attributes["symbols"]
        assert "storage" in concept.attributes["symbols"]

    def test_symbols_extracted_snake_case(self):
        concept = _encode_session_concept(
            "Updated handle_mcp_tool and session_factory", "test"
        )
        assert "handle" in concept.attributes["symbols"]
        assert "session" in concept.attributes["symbols"]

    def test_summary_is_truncated(self):
        concept = _encode_session_concept("word " * 100, "test")
        summary_words = concept.attributes["summary"].split()
        assert len(summary_words) <= 20


# ---------------------------------------------------------------------------
# Encoder config shape
# ---------------------------------------------------------------------------

class TestSessionEncoderConfig:

    def test_has_content_layer(self):
        layer_names = [l.name for l in SESSION_ENCODER_CONFIG.layers]
        assert "content" in layer_names

    def test_has_context_layer(self):
        layer_names = [l.name for l in SESSION_ENCODER_CONFIG.layers]
        assert "context" in layer_names

    def test_temporal_enabled(self):
        assert SESSION_ENCODER_CONFIG.include_temporal is True

    def test_dimension(self):
        assert SESSION_ENCODER_CONFIG.dimension == 2000

    def test_different_seed_from_file_index(self):
        from glyphh_code.encoder import ENCODER_CONFIG
        assert SESSION_ENCODER_CONFIG.seed != ENCODER_CONFIG.seed


# ---------------------------------------------------------------------------
# Content layer similarity — semantic clustering
# ---------------------------------------------------------------------------

class TestContentLayerSimilarity:

    def test_similar_notes_high_content_sim(self, encoder):
        """Notes about the same topic should cluster at content layer."""
        g1 = _encode_note(encoder, "Refactored auth middleware to validate JWT tokens", "a")
        g2 = _encode_note(encoder, "Auth middleware now checks JWT token expiry", "b")
        sim = cosine_similarity(
            g1.layers["content"].cortex.data,
            g2.layers["content"].cortex.data,
        )
        assert sim > 0.2, f"Similar notes content sim should be > 0.2, got {sim:.3f}"

    def test_unrelated_notes_low_content_sim(self, encoder):
        """Notes about different topics should have low content layer sim."""
        g1 = _encode_note(encoder, "Refactored auth middleware to validate JWT tokens", "a")
        g2 = _encode_note(encoder, "Database migration adds index on created_at column", "b")
        sim = cosine_similarity(
            g1.layers["content"].cortex.data,
            g2.layers["content"].cortex.data,
        )
        assert sim < 0.2, f"Unrelated notes content sim should be < 0.2, got {sim:.3f}"

    def test_same_content_identical_content_layer(self, encoder):
        """Same content → identical content layer vectors (deterministic)."""
        content = "Session memory encoding pipeline for code model"
        g1 = _encode_note(encoder, content, "a")
        g2 = _encode_note(encoder, content, "b")
        sim = cosine_similarity(
            g1.layers["content"].cortex.data,
            g2.layers["content"].cortex.data,
        )
        assert sim == pytest.approx(1.0, abs=0.001)

    def test_recall_ranks_relevant_note_first(self, encoder):
        """A recall query should score highest on the relevant note."""
        notes = {
            "auth": _encode_note(encoder, "Auth middleware validates JWT tokens and checks expiry", "auth"),
            "db": _encode_note(encoder, "Database connection pool uses asyncpg with max 20 connections", "db"),
            "api": _encode_note(encoder, "REST API endpoints defined in routes api with FastAPI", "api"),
        }
        query = _encode_note(encoder, "JWT token validation in middleware", "q")

        sims = {
            label: cosine_similarity(
                query.layers["content"].cortex.data,
                g.layers["content"].cortex.data,
            )
            for label, g in notes.items()
        }
        assert sims["auth"] > sims["db"], f"auth ({sims['auth']:.3f}) should beat db ({sims['db']:.3f})"
        assert sims["auth"] > sims["api"], f"auth ({sims['auth']:.3f}) should beat api ({sims['api']:.3f})"


# ---------------------------------------------------------------------------
# Context layer similarity — file path and symbol recall
# ---------------------------------------------------------------------------

class TestContextLayerSimilarity:

    def test_file_path_mention_boosts_context_sim(self, encoder):
        """Notes mentioning the same file paths should cluster at context layer."""
        g1 = _encode_note(encoder, "Changed glyphh_code/encoder.py to add session tools", "a")
        g2 = _encode_note(encoder, "Updated glyphh_code/encoder.py with new MCP handlers", "b")
        g3 = _encode_note(encoder, "Updated the deployment pipeline scripts", "c")

        query = _encode_note(encoder, "encoder.py session changes", "q")

        sim_a = cosine_similarity(
            query.layers["context"].cortex.data,
            g1.layers["context"].cortex.data,
        )
        sim_c = cosine_similarity(
            query.layers["context"].cortex.data,
            g3.layers["context"].cortex.data,
        )
        assert sim_a > sim_c, f"Path-matching ({sim_a:.3f}) should beat unrelated ({sim_c:.3f})"

    def test_shared_symbols_high_context_sim(self, encoder):
        """Notes mentioning the same snake_case symbols should have high context sim."""
        g1 = _encode_note(encoder, "The handle_mcp_tool function dispatches session_write calls", "a")
        g2 = _encode_note(encoder, "Fixed handle_mcp_tool to route session_write correctly", "b")
        sim = cosine_similarity(
            g1.layers["context"].cortex.data,
            g2.layers["context"].cortex.data,
        )
        assert sim > 0.3, f"Shared symbols context sim should be > 0.3, got {sim:.3f}"


# ---------------------------------------------------------------------------
# Temporal layer — notes at different times should differ
# ---------------------------------------------------------------------------

class TestTemporalLayer:

    def test_temporal_layer_exists(self, encoder):
        g = _encode_note(encoder, "Some session note", "a")
        assert "_temporal" in g.layers

    def test_glyph_has_timestamp_in_identifier(self, encoder):
        g = _encode_note(encoder, "Some session note", "a")
        assert "@" in g.identifier, "Temporal glyph should have @ in identifier"


# ---------------------------------------------------------------------------
# Layer-weighted scoring (simulates recall handler logic)
# ---------------------------------------------------------------------------

class TestSessionScore:

    def test_combined_score_ranks_correctly(self, encoder):
        """Adaptive scoring should rank the most relevant note first."""
        auth_text = "Refactored glyphh_code/encoder.py auth middleware JWT validation"
        db_text = "Database migration adds index on users table created_at"
        query_text = "encoder.py JWT auth changes"

        auth_glyph = _encode_note(encoder, auth_text, "auth")
        db_glyph = _encode_note(encoder, db_text, "db")
        query_glyph = _encode_note(encoder, query_text, "q")

        auth_score = _session_score(query_glyph, auth_glyph, query_text, auth_text)
        db_score = _session_score(query_glyph, db_glyph, query_text, db_text)

        assert auth_score["combined"] > db_score["combined"], (
            f"auth ({auth_score['combined']:.3f}) should beat db ({db_score['combined']:.3f})"
        )

    def test_empty_context_does_not_dominate(self, encoder):
        """Empty context roles must not produce degenerate cosine 1.0 matches.

        Queries without file paths or code symbols should score purely on
        content similarity, not spuriously match notes via empty-BoW vectors.
        """
        # Note with rich context (file paths, symbols)
        rich_text = "Updated glyphh_code/encoder.py with BeamSearchPredictor temporal tracking"
        # Note with matching content but no context
        matching_text = "Fixed the search feature to handle temporal queries correctly"
        # Query with no context signals (no .py paths, no camelCase, no snake_case)
        query_text = "search feature fix"

        rich_glyph = _encode_note(encoder, rich_text, "rich")
        matching_glyph = _encode_note(encoder, matching_text, "matching")
        query_glyph = _encode_note(encoder, query_text, "q")

        rich_score = _session_score(query_glyph, rich_glyph, query_text, rich_text)
        matching_score = _session_score(query_glyph, matching_glyph, query_text, matching_text)

        # Matching note should score higher — its content overlaps with the query
        assert matching_score["combined"] > rich_score["combined"], (
            f"matching ({matching_score['combined']:.3f}) should beat rich ({rich_score['combined']:.3f})"
        )
        # Context should be 0 for both (query has no context signals)
        assert rich_score["context"] == 0.0
        assert matching_score["context"] == 0.0

    def test_shared_symbols_boost_score(self, encoder):
        """Notes sharing code symbols with the query should score higher via context."""
        target_text = "The handle_mcp_tool function dispatches session_write calls"
        other_text = "Database connection pool uses asyncpg with max 20 connections"
        query_text = "handle_mcp_tool routing"

        target_glyph = _encode_note(encoder, target_text, "target")
        other_glyph = _encode_note(encoder, other_text, "other")
        query_glyph = _encode_note(encoder, query_text, "q")

        target_score = _session_score(query_glyph, target_glyph, query_text, target_text)
        other_score = _session_score(query_glyph, other_glyph, query_text, other_text)

        assert target_score["combined"] > other_score["combined"], (
            f"target ({target_score['combined']:.3f}) should beat other ({other_score['combined']:.3f})"
        )
        assert target_score["context"] > 0, "Shared symbols should produce positive context sim"
