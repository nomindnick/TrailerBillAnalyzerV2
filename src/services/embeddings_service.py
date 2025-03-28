import logging
import asyncio
import numpy as np
from typing import List, Dict, Any, Tuple, Optional, Union
import os
import json
import hashlib
from pathlib import Path

class EmbeddingsService:
    """
    Service for generating and managing embeddings for text comparison.
    Provides caching and batching for improved performance and cost efficiency.
    """

    def __init__(self, openai_client, embedding_model="text-embedding-3-large", embedding_dimensions=None, cache_dir="embeddings_cache"):
        """
        Initialize the embeddings service.

        Args:
            openai_client: An initialized OpenAI async client
            embedding_model: The embedding model to use (default: text-embedding-3-large)
            embedding_dimensions: Optional dimension reduction for embeddings (default: None = full dimensions)
            cache_dir: Directory to store cached embeddings
        """
        self.logger = logging.getLogger(__name__)
        self.openai_client = openai_client
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions

        # Set up caching
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cache = {}
        self.load_cache()

        # Determine embedding dimensions based on model
        if self.embedding_dimensions is None:
            if "small" in self.embedding_model:
                self.full_dimensions = 1536
            elif "large" in self.embedding_model:
                self.full_dimensions = 3072
            else:  # Default for older models
                self.full_dimensions = 1536
        else:
            self.full_dimensions = self.embedding_dimensions

        self.logger.info(f"Initialized EmbeddingsService with model {embedding_model} and dimensions {self.full_dimensions}")

    def load_cache(self):
        """Load the embeddings cache from disk"""
        try:
            cache_file = self.cache_dir / "embeddings_cache.json"
            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    self.cache = json.load(f)
                self.logger.info(f"Loaded {len(self.cache)} cached embeddings")
            else:
                self.logger.info("No cache file found, starting with empty cache")
        except Exception as e:
            self.logger.warning(f"Error loading embeddings cache: {str(e)}")
            self.cache = {}

    def save_cache(self):
        """Save the embeddings cache to disk"""
        try:
            cache_file = self.cache_dir / "embeddings_cache.json"
            with open(cache_file, 'w') as f:
                json.dump(self.cache, f)
            self.logger.info(f"Saved {len(self.cache)} embeddings to cache")
        except Exception as e:
            self.logger.warning(f"Error saving embeddings cache: {str(e)}")

    def _get_cache_key(self, text: str, model: str, dimensions: Optional[int] = None) -> str:
        """Generate a unique cache key for a text and model combination"""
        # Create a hash that includes the text, model name, and dimensions
        hash_input = f"{text}|{model}|{dimensions}"
        return hashlib.md5(hash_input.encode('utf-8')).hexdigest()

    async def get_embedding(self, text: str, normalize: bool = True) -> List[float]:
        """
        Get an embedding for a single text string with caching

        Args:
            text: The text to embed
            normalize: Whether to normalize the embedding vector (default: True)

        Returns:
            List of floats representing the embedding
        """
        if not text or not text.strip():
            self.logger.warning("Attempted to get embedding for empty text")
            # Return zero vector of appropriate length
            return [0.0] * self.full_dimensions

        # Clean and truncate text if very long
        text = text.replace("\n", " ").strip()

        # Check if we have this embedding cached
        cache_key = self._get_cache_key(text, self.embedding_model, self.embedding_dimensions)
        if cache_key in self.cache:
            embedding = self.cache[cache_key]
            return embedding

        try:
            # Get embedding from OpenAI
            response = await self.openai_client.embeddings.create(
                model=self.embedding_model,
                input=text,
                dimensions=self.embedding_dimensions
            )

            embedding = response.data[0].embedding

            # Normalize if requested
            if normalize:
                embedding = self._normalize_embedding(embedding)

            # Cache the embedding
            self.cache[cache_key] = embedding

            # Periodically save cache (every 100 new embeddings)
            if len(self.cache) % 100 == 0:
                self.save_cache()

            return embedding

        except Exception as e:
            self.logger.error(f"Error getting embedding: {str(e)}")
            raise

    async def get_embeddings_batch(self, texts: List[str], normalize: bool = True) -> List[List[float]]:
        """
        Get embeddings for a batch of texts with caching

        Args:
            texts: List of texts to embed
            normalize: Whether to normalize the embedding vectors

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        embeddings = []
        texts_to_embed = []
        indices_to_embed = []

        # Check cache first for each text
        for i, text in enumerate(texts):
            if not text or not text.strip():
                embeddings.append([0.0] * self.full_dimensions)
                continue

            # Clean text
            text = text.replace("\n", " ").strip()

            # Check cache
            cache_key = self._get_cache_key(text, self.embedding_model, self.embedding_dimensions)
            if cache_key in self.cache:
                embeddings.append(self.cache[cache_key])
            else:
                # Save position for later insertion
                texts_to_embed.append(text)
                indices_to_embed.append(i)
                # Add placeholder
                embeddings.append(None)

        # If we have texts not in cache, get embeddings from API
        if texts_to_embed:
            try:
                # Split into batches of 1000 if needed (OpenAI limit)
                batch_size = 1000
                all_new_embeddings = []

                for i in range(0, len(texts_to_embed), batch_size):
                    batch = texts_to_embed[i:i+batch_size]
                    response = await self.openai_client.embeddings.create(
                        model=self.embedding_model,
                        input=batch,
                        dimensions=self.embedding_dimensions
                    )
                    batch_embeddings = [item.embedding for item in response.data]
                    all_new_embeddings.extend(batch_embeddings)

                # Normalize if requested
                if normalize:
                    all_new_embeddings = [self._normalize_embedding(emb) for emb in all_new_embeddings]

                # Insert new embeddings and update cache
                for idx, embedding in zip(indices_to_embed, all_new_embeddings):
                    text = texts[idx]
                    cache_key = self._get_cache_key(text, self.embedding_model, self.embedding_dimensions) 
                    self.cache[cache_key] = embedding
                    embeddings[idx] = embedding

                # Save cache
                if len(texts_to_embed) > 0:
                    self.save_cache()

            except Exception as e:
                self.logger.error(f"Error getting batch embeddings: {str(e)}")
                # Fill remaining embeddings with zeros as a fallback
                for idx in indices_to_embed:
                    if embeddings[idx] is None:
                        embeddings[idx] = [0.0] * self.full_dimensions
                raise

        return embeddings

    def _normalize_embedding(self, embedding: List[float]) -> List[float]:
        """
        Normalize an embedding vector to unit length

        Args:
            embedding: The embedding vector to normalize

        Returns:
            Normalized embedding vector
        """
        embedding_array = np.array(embedding)
        norm = np.linalg.norm(embedding_array)
        if norm > 0:
            return (embedding_array / norm).tolist()
        return embedding  # Return as-is if norm is 0

    def cosine_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """
        Calculate cosine similarity between two embeddings

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Cosine similarity score (0-1, higher is more similar)
        """
        # Convert to numpy arrays
        embedding1 = np.array(embedding1)
        embedding2 = np.array(embedding2)

        # Calculate dot product
        dot_product = np.dot(embedding1, embedding2)

        # Calculate magnitudes
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)

        # Calculate cosine similarity
        if norm1 > 0 and norm2 > 0:
            return dot_product / (norm1 * norm2)
        return 0.0

    async def find_best_matches(
        self, 
        query_text: str, 
        candidate_texts: List[str], 
        top_n: int = 1
    ) -> List[Tuple[int, float]]:
        """
        Find the best matches from candidate_texts for a query_text.

        Args:
            query_text: The text to find matches for
            candidate_texts: List of candidate texts to match against
            top_n: Number of top matches to return (default: 1)

        Returns:
            List of tuples containing (index, similarity score)
        """
        # Get embeddings
        query_embedding = await self.get_embedding(query_text)
        candidate_embeddings = await self.get_embeddings_batch(candidate_texts)

        # Calculate similarities
        similarities = []
        for i, candidate_embedding in enumerate(candidate_embeddings):
            similarity = self.cosine_similarity(query_embedding, candidate_embedding)
            similarities.append((i, similarity))

        # Sort by similarity and return top N
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_n]

    async def find_best_matches_from_embeddings(
        self, 
        query_embedding: List[float], 
        candidate_embeddings: List[List[float]], 
        top_n: int = 1
    ) -> List[Tuple[int, float]]:
        """
        Find the best matches from candidate_embeddings for a query_embedding.

        Args:
            query_embedding: The embedding to find matches for
            candidate_embeddings: List of candidate embeddings to match against
            top_n: Number of top matches to return (default: 1)

        Returns:
            List of tuples containing (index, similarity score)
        """
        # Calculate similarities
        similarities = []
        for i, candidate_embedding in enumerate(candidate_embeddings):
            similarity = self.cosine_similarity(query_embedding, candidate_embedding)
            similarities.append((i, similarity))

        # Sort by similarity and return top N
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_n]