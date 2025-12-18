#!/usr/bin/env python3
"""
Shared configuration for KG-Microbe visualization scripts.

This module contains common settings used across all visualization scripts
to ensure consistency and avoid code duplication.
"""

# Node category color scheme
# Maps Biolink/METPO categories to hex color codes for visualization
CATEGORY_COLORS = {
    'biolink:OrganismTaxon': '#FF6B6B',         # Red
    'biolink:ChemicalEntity': '#4ECDC4',        # Teal
    'biolink:ChemicalMixture': '#45B7D1',       # Blue
    'METPO:1004005': '#45B7D1',                 # Growth medium (same as ChemicalMixture)
    'biolink:Enzyme': '#96CEB4',                # Green
    'biolink:PhenotypicQuality': '#FFEAA7',     # Yellow
    'biolink:EnvironmentalFeature': '#DDA0DD',  # Purple
    'biolink:ActivityAndBehavior': '#FFB347'    # Orange
}

# Figure size defaults
FIGURE_SIZE_1HOP = (30, 30)
FIGURE_SIZE_2HOP = (35, 30)

# Output DPI (dots per inch) for high-resolution images
OUTPUT_DPI = 300
