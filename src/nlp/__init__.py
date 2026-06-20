"""NLP pipeline for the Hirenovik project.

Modules:
    preprocess: Supabase description loader and text cleaner.
    embedder: Sentence-transformers embedder with disk cache.
    topic_model: BERTopic topic model with DB assignment.
    search_engine: FAISS search engine with iterative query expansion.
    trends: Weekly topic trend computation.
    pipeline: Orchestrates the full NLP pipeline.
"""

from src.nlp.preprocess import TextPreprocessor

__all__ = ["TextPreprocessor"]