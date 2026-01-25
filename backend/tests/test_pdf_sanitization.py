"""
Tests for PDF Sanitization.

HARD CONSTRAINT: These tests verify compliance with Section 2 of the Hard Constraint Spec.
Tests that SHOULD FAIL are marked as such - they validate failure paths.
"""

import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.pdf_renderer import PDFRenderer


class TestSanitizeLatex:
    """Tests for _sanitize_latex method."""
    
    def setup_method(self):
        self.renderer = PDFRenderer(output_dir="/tmp/test_pdf")
    
    # --- Tests that MUST PASS ---
    
    def test_escapes_ampersand(self):
        """Ampersand must be escaped."""
        result = self.renderer._sanitize_latex("Solution Key & Grading Rubric")
        assert r"\&" in result
        assert "&" not in result.replace(r"\&", "")
    
    def test_escapes_percent(self):
        """Percent must be escaped."""
        result = self.renderer._sanitize_latex("Score: 85%")
        assert r"\%" in result
    
    def test_escapes_hash(self):
        """Hash must be escaped."""
        result = self.renderer._sanitize_latex("Question #1")
        assert r"\#" in result
    
    def test_escapes_underscore(self):
        """Underscore must be escaped."""
        result = self.renderer._sanitize_latex("variable_name")
        assert r"\_" in result
    
    def test_empty_string(self):
        """Empty string returns empty."""
        result = self.renderer._sanitize_latex("")
        assert result == ""
    
    def test_none_returns_empty(self):
        """None returns empty string."""
        result = self.renderer._sanitize_latex(None)
        assert result == ""
    
    def test_plain_text_unchanged(self):
        """Plain text without special chars is unchanged."""
        result = self.renderer._sanitize_latex("Hello World")
        assert result == "Hello World"
    
    def test_multiple_special_chars(self):
        """Multiple special characters all escaped."""
        result = self.renderer._sanitize_latex("Q#1: A & B = 100%")
        assert r"\#" in result
        assert r"\&" in result
        assert r"\%" in result


class TestValidateMathContent:
    """Tests for _validate_math_content method."""
    
    def setup_method(self):
        self.renderer = PDFRenderer(output_dir="/tmp/test_pdf")
    
    def test_valid_inline_math(self):
        """Valid inline math passes."""
        # Should not raise
        self.renderer._validate_math_content("The formula is $x^2 + y^2 = r^2$")
    
    def test_valid_block_math(self):
        """Valid block math passes."""
        # Should not raise
        self.renderer._validate_math_content("$$\\int_0^1 x dx$$")
    
    def test_empty_string_passes(self):
        """Empty string passes validation."""
        # Should not raise
        self.renderer._validate_math_content("")
    
    def test_unbalanced_delimiters_fails(self):
        """Unbalanced $ delimiters must fail."""
        with pytest.raises(ValueError) as exc_info:
            self.renderer._validate_math_content("The formula is $x^2 + y^2")
        assert "unbalanced" in str(exc_info.value).lower()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
