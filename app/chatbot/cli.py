"""Command line interface for Chatbot management and tuning."""
import argparse
import json
import logging
import sys
from pathlib import Path

from .config import cfg
from .rag import rag_engine
from .models import init_db, get_db_session, ChatKbChunk

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("chatbot.cli")


def handle_ingest(args):
    """Subcommand: ingest (optional --force)."""
    force = getattr(args, "force", False)
    print(f"Starting knowledge base ingestion (force={force})...")
    res = rag_engine.ingest(force=force)
    print(f"Ingest complete: {res['created']} created, {res['updated']} updated, {res['deleted']} deleted, {res['unchanged']} unchanged.")


def handle_eval(args):
    """Subcommand: eval (reads eval_questions.json and measures retrieval hit rate and scores)."""
    eval_file = Path(__file__).resolve().parent / "eval_questions.json"
    if not eval_file.exists():
        print(f"Eval file not found at {eval_file}")
        sys.exit(1)

    with open(eval_file, "r", encoding="utf-8") as f:
        questions = json.load(f)

    print(f"Running evaluation on {len(questions)} test questions...")
    k = cfg.RAG_TOP_K
    hits_at_k = 0

    for item in questions:
        q = item["question"]
        expected_chunk_id = item["expected_chunk_id"]

        results = rag_engine.retrieve(q, k=k)
        result_ids = [r.id for r in results]

        is_hit = expected_chunk_id in result_ids
        if is_hit:
            hits_at_k += 1

        correct_score = next((r.score for r in results if r.id == expected_chunk_id), None)
        incorrect_scores = [r.score for r in results if r.id != expected_chunk_id]
        best_incorrect = max(incorrect_scores) if incorrect_scores else 0.0

        print(
            f"Question: '{q[:40]}...' | Target: {expected_chunk_id} | Hit@{k}: {is_hit} | "
            f"Correct Score: {correct_score} | Best Incorrect: {best_incorrect}"
        )

    hit_rate = (hits_at_k / len(questions)) * 100 if questions else 0.0
    print(f"\n==========================================")
    print(f"Hit rate @ {k}: {hit_rate:.1f}% ({hits_at_k}/{len(questions)})")
    print(f"Active RAG_MIN_SIMILARITY threshold: {cfg.RAG_MIN_SIMILARITY}")
    print(f"==========================================")


def handle_health(args):
    """Subcommand: health (prints configuration status without secrets)."""
    init_db()
    db = get_db_session()
    chunk_count = 0
    try:
        chunk_count = db.query(ChatKbChunk).count()
    finally:
        db.close()

    mode = "full" if cfg.has_gemini_key else "limited"
    embeddings_status = "active (Gemini API key present)" if cfg.has_gemini_key else "fallback (keyword search BM25)"

    print("--- TradeZen Chatbot Health & Config ---")
    print(f"Mode: {mode}")
    print(f"Embeddings Status: {embeddings_status}")
    print(f"Chat Model: {cfg.GEMINI_CHAT_MODEL}")
    print(f"Embedding Model: {cfg.GEMINI_EMBED_MODEL}")
    print(f"Knowledge Directory: {cfg.knowledge_dir.name}")
    print(f"Knowledge Chunks in DB: {chunk_count}")
    print(f"RAG Top K: {cfg.RAG_TOP_K}")
    print(f"RAG Min Similarity: {cfg.RAG_MIN_SIMILARITY}")
    print(f"Circuit Breaker Status: {'Available'}")
    print("----------------------------------------")


def handle_llm_check(args):
    """Subcommand: llm-check.
    Prints model used, status, tiny call result (status, error class, elapsed ms),
    and discovered usable model names.
    No keys, no prompt text, no trade values.
    """
    import time
    from .llm import llm_client, get_model_health_status, _list_usable_generate_models

    print("--- TradeZen LLM Diagnostic Check ---")

    client = llm_client._get_client()
    if client is None:
        print("Status: NO_KEY — GEMINI_API_KEY not set or client unavailable")
        return

    # Model health (cached, never raises)
    try:
        mh = get_model_health_status(cfg, client)
        print(f"Chat model       : {mh.get('chat_model', 'unset')}")
        print(f"Chat model status: {mh.get('chat_model_status', 'unknown')}")
        print(f"Embed model      : {mh.get('embed_model', 'unset')}")
        print(f"Embed model status: {mh.get('embed_model_status', 'unknown')}")
        discovered = mh.get("discovered_usable_models", [])
        print(f"Discovered models ({len(discovered)}): {', '.join(discovered) or 'none'}")
    except Exception as exc:
        print(f"Model health check failed: {type(exc).__name__}")

    # 1. Tiny call
    t0 = time.monotonic()
    res1 = llm_client.generate(
        system="Be concise.",
        messages=[{"role": "user", "content": "ping"}],
        max_output_tokens=10,
        flow="general"
    )
    ms1 = int((time.monotonic() - t0) * 1000)
    status1 = "OK" if res1.ok else "FAILED"
    err1 = res1.error_kind if not res1.ok else "None"
    model1 = res1.model_used or "None"
    print(f"Tiny call: status={status1} error_class={err1} model={model1} elapsed_ms={ms1}")

    # 2. Full pipeline call
    user_id = getattr(args, "user_id", 1) or 1
    t0 = time.monotonic()
    try:
        from .brain import answer
        ans = answer(user_id=user_id, message="hi")
        ms2 = int((time.monotonic() - t0) * 1000)
        status2 = "OK" if not ans.get("degraded", False) else "DEGRADED"
        err2 = ans.get("degraded_reason") or "None"
        route2 = ans.get("route", "UNKNOWN")
        genby2 = ans.get("generated_by", "?")
        print(f"Pipeline call: status={status2} route={route2} generated_by={genby2} error_class={err2} elapsed_ms={ms2}")
    except Exception as exc:
        ms2 = int((time.monotonic() - t0) * 1000)
        print(f"Pipeline call: status=EXCEPTION error_class={type(exc).__name__} elapsed_ms={ms2}")

    print("--------------------------------------")


def main():
    parser = argparse.ArgumentParser(description="TradeZen Chatbot CLI")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Ingest parser
    ingest_parser = subparsers.add_parser("ingest", help="Ingest knowledge markdown files into database")
    ingest_parser.add_argument("--force", action="store_true", help="Force re-embedding of unchanged chunks")

    # Eval parser
    subparsers.add_parser("eval", help="Evaluate RAG retrieval accuracy against eval_questions.json")

    # Health parser
    subparsers.add_parser("health", help="Check chatbot health and configuration status")

    # LLM Check parser
    llm_check_parser = subparsers.add_parser("llm-check", help="Run diagnostic checks on Gemini connectivity")
    llm_check_parser.add_argument("--user-id", type=int, default=1, help="User ID for full pipeline check")

    args = parser.parse_args()
    if args.subcommand == "ingest":
        handle_ingest(args)
    elif args.subcommand == "eval":
        handle_eval(args)
    elif args.subcommand == "health":
        handle_health(args)
    elif args.subcommand == "llm-check":
        handle_llm_check(args)


if __name__ == "__main__":
    main()
