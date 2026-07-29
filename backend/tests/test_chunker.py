from synsc.core.chunker import CodeChunker


def test_code_chunker_treats_tokenizer_sentinels_as_source_text() -> None:
    chunker = CodeChunker(quality_mode="agent")
    source = 'const endOfText = "<|endoftext|>";'

    chunks = chunker.chunk_file(source, language="typescript")

    assert len(chunks) == 1
    assert chunks[0].content == source
    assert chunks[0].token_count == 12
