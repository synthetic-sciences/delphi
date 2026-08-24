from synsc.core.chunker import CodeChunker


def test_code_chunker_treats_tokenizer_sentinels_as_source_text() -> None:
    chunker = CodeChunker(quality_mode="agent")
    source = 'const endOfText = "<|endoftext|>";'

    chunks = chunker.chunk_file(source, language="typescript")

    assert len(chunks) == 1
    assert chunks[0].content == source
    assert chunks[0].token_count == 12


def test_code_chunker_hard_splits_single_lines_over_token_limit() -> None:
    chunker = CodeChunker(quality_mode="agent")
    chunker.max_tokens = 32
    chunker.min_chunk_tokens = 1
    source = " ".join(f"token_{index}" for index in range(200))

    chunks = chunker.chunk_file(source, language="python")

    assert len(chunks) > 1
    assert "".join(chunk.content for chunk in chunks) == source
    assert all(chunk.token_count <= chunker.max_tokens for chunk in chunks)
    assert all((chunk.start_line, chunk.end_line) == (1, 1) for chunk in chunks)
