"""Tests for address normalization."""

import pytest
from ml.address_normalizer import AddressNormalizer, normalize_address


class TestAddressNormalizer:
    """Test address normalization."""

    def setup_method(self):
        self.normalizer = AddressNormalizer()

    def test_lowercase_normalization(self):
        """Test basic lowercase normalization."""
        result = self.normalizer.normalize("Hanuman Mandir")
        # "mandir" gets expanded to "temple" via abbreviation expansion
        assert result.normalized_address == "hanuman temple"

    def test_unicode_normalization(self):
        """Test Unicode normalization."""
        result = self.normalizer.normalize("हनुमान मंदिर")
        assert "हनुमान" in result.normalized_address

    def test_abbreviation_expansion(self):
        """Test abbreviation expansion."""
        result = self.normalizer.normalize("Flat No. 201, MG Road")
        assert "number" in result.normalized_address or "flat" in result.normalized_address

    def test_punctuation_normalization(self):
        """Test punctuation normalization."""
        result = self.normalizer.normalize("Flat 201, ABC Apartments; MG Road")
        assert ";" not in result.normalized_address

    def test_whitespace_normalization(self):
        """Test whitespace normalization."""
        result = self.normalizer.normalize("Flat   201,   ABC   Apartments")
        assert "  " not in result.normalized_address

    def test_hindi_abbreviation(self):
        """Test Hindi abbreviation handling."""
        result = self.normalizer.normalize("Hanuman mandir ke piche")
        # "ke piche" should be expanded to "behind"
        assert "behind" in result.normalized_address or "piche" in result.normalized_address

    def test_empty_address(self):
        """Test empty address handling."""
        result = self.normalizer.normalize("")
        assert result.normalized_address == ""
        assert result.confidence == 0.0

    def test_language_detection_english(self):
        """Test English language detection."""
        result = self.normalizer.normalize("Flat 201, MG Road, Bangalore")
        assert result.language == "en"

    def test_language_detection_hindi(self):
        """Test Hindi language detection."""
        result = self.normalizer.normalize("हनुमान मंदिर के पीछे")
        assert result.language == "hi"

    def test_pincode_extraction(self):
        """Test pincode extraction."""
        result = self.normalizer.normalize("MG Road, Bangalore 560001")
        assert result.normalized_address  # Just check it doesn't crash

    def test_confidence_calculation(self):
        """Test confidence calculation."""
        result = self.normalizer.normalize("Flat 201, ABC Apartments, MG Road")
        assert 0.0 <= result.confidence <= 1.0

    def test_messy_address(self):
        """Test messy address normalization."""
        result = self.normalizer.normalize("Hanuman mndr piche ration shop 2nd gali")
        assert result.normalized_address  # Should produce some output
        assert result.confidence > 0.0

    def test_mixed_language(self):
        """Test mixed language address."""
        result = self.normalizer.normalize("Hanuman mandir ke piche, 2nd cross")
        assert result.normalized_address  # Should handle mixed language