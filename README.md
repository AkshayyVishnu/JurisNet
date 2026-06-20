# JurisNet
JurisNet is our submission for the IIT Kharagpur The Arch: RAG and Agentic AI Hackathon, built for the Legal Services track.



JurisNet is a multi-agent Agentic RAG system with an integrated legal knowledge graph, designed specifically for the Indian common law system. Rather than treating case law as a flat document collection, JurisNet models Indian Kanoon judgments, statutes, and precedents as interconnected graph nodes — enabling agents to reason across court hierarchies, detect overruled precedents, and handle multi-hop temporal queries that break every standard RAG pipeline.
The system combines hybrid BM25 + dense retrieval, cross-encoder reranking, GraphRAG traversal, and a self-reflective faithfulness verification loop — evaluated against a manually annotated  gold set using deterministic span-level Precision@k and Recall@k metrics following the LegalBench-RAG methodology, adapted for the first time to an Indian legal corpus.
