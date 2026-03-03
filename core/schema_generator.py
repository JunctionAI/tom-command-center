#!/usr/bin/env python3
"""
Schema Generator — DietarySupplement + FAQPage JSON-LD for SEO.

Used by Beacon to generate structured data for blog articles.
Helps with rich snippets and AI citation discovery.
"""

import json


def generate_supplement_schema(product_name: str, description: str,
                                benefits: list, dosage: str = "",
                                brand: str = "Deep Blue Health",
                                url: str = "") -> str:
    """
    Generate DietarySupplement schema.org JSON-LD.

    Args:
        product_name: e.g. "Green Lipped Mussel Extract 19000mg"
        description: Product description
        benefits: List of health benefit strings
        dosage: e.g. "1 capsule daily with food"
        brand: Brand name
        url: Product page URL

    Returns:
        JSON-LD string
    """
    schema = {
        "@context": "https://schema.org",
        "@type": "DietarySupplement",
        "name": product_name,
        "description": description,
        "brand": {
            "@type": "Brand",
            "name": brand
        },
        "manufacturer": {
            "@type": "Organization",
            "name": brand,
            "address": {
                "@type": "PostalAddress",
                "addressCountry": "NZ",
                "addressLocality": "Auckland"
            }
        },
    }

    if benefits:
        schema["activeIngredient"] = ", ".join(benefits)

    if dosage:
        schema["recommendedIntake"] = {
            "@type": "RecommendedDoseSchedule",
            "frequency": dosage
        }

    if url:
        schema["url"] = url

    return json.dumps(schema, indent=2)


def generate_faq_schema(faqs: list) -> str:
    """
    Generate FAQPage schema.org JSON-LD.

    Args:
        faqs: List of dicts with 'question' and 'answer' keys

    Returns:
        JSON-LD string
    """
    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": []
    }

    for faq in faqs:
        schema["mainEntity"].append({
            "@type": "Question",
            "name": faq["question"],
            "acceptedAnswer": {
                "@type": "Answer",
                "text": faq["answer"]
            }
        })

    return json.dumps(schema, indent=2)


def generate_article_schema(title: str, description: str,
                             author: str = "Deep Blue Health",
                             date_published: str = "",
                             url: str = "",
                             image_url: str = "") -> str:
    """
    Generate Article schema.org JSON-LD.
    """
    from datetime import date as d

    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description,
        "author": {
            "@type": "Organization",
            "name": author
        },
        "publisher": {
            "@type": "Organization",
            "name": "Deep Blue Health",
            "url": "https://deepbluehealth.co.nz"
        },
        "datePublished": date_published or d.today().isoformat(),
    }

    if url:
        schema["url"] = url
    if image_url:
        schema["image"] = image_url

    return json.dumps(schema, indent=2)


def combine_schemas(*schemas: str) -> str:
    """
    Combine multiple JSON-LD schemas into script tags for HTML injection.

    Args:
        *schemas: JSON-LD strings

    Returns:
        HTML script tags containing all schemas
    """
    tags = []
    for schema in schemas:
        tags.append(f'<script type="application/ld+json">\n{schema}\n</script>')
    return "\n".join(tags)


if __name__ == "__main__":
    # Example usage
    supp = generate_supplement_schema(
        product_name="Green Lipped Mussel Extract 19000mg",
        description="Premium New Zealand Green Lipped Mussel supplement for joint health support",
        benefits=["Joint mobility support", "Anti-inflammatory properties", "Omega-3 fatty acids"],
        dosage="1 capsule daily with food",
        url="https://deepbluehealth.co.nz/products/green-lipped-mussel"
    )

    faq = generate_faq_schema([
        {"question": "What is Green Lipped Mussel?",
         "answer": "Green Lipped Mussel (Perna canaliculus) is a shellfish native to New Zealand, rich in omega-3 fatty acids and known for supporting joint health."},
        {"question": "How should I take Green Lipped Mussel supplements?",
         "answer": "Take 1 capsule daily with food for best absorption."},
    ])

    html = combine_schemas(supp, faq)
    print(html)
