"use client";

import { useState } from "react";
import AnswerView from "./components/AnswerView";
import { askResearch, type AskResponse } from "@/lib/api";

const TICKERS = ["NVDA", "AMD", "INTC"] as const;
type Ticker = (typeof TICKERS)[number];

const SAMPLE_QUESTIONS: Record<Ticker, string[]> = {
  NVDA: [
    "What does NVIDIA identify as its primary data center competition in its most recent 10-K?",
    "What risks does NVIDIA disclose from U.S. export controls affecting sales to China?",
    "What was NVIDIA's revenue growth and gross margin last year?",
    "What is NVIDIA's 3-year revenue CAGR?",
  ],
  AMD: [
    "What product segments does AMD operate in, as described in its latest 10-K?",
    "How does AMD describe its strategy for AI accelerators?",
    "What was AMD's operating margin last fiscal year?",
  ],
  INTC: [
    "What does Intel disclose about its foundry (IFS) strategy?",
    "Does Intel disclose material customer concentration risk?",
    "What was Intel's free cash flow last fiscal year?",
  ],
};

export default function Home() {
  const [ticker, setTicker] = useState<Ticker>("NVDA");
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await askResearch(ticker, question));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-12">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">AI Equity Research</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Ask a question about a company&apos;s most recent 10-K. Every claim is cited back to the
          underlying passage.
        </p>
      </header>

      <form onSubmit={submit} className="space-y-4">
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium" htmlFor="ticker">
            Ticker
          </label>
          <select
            id="ticker"
            value={ticker}
            onChange={(e) => setTicker(e.target.value as Ticker)}
            className="rounded-md border border-neutral-300 bg-white px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          >
            {TICKERS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium" htmlFor="question">
            Question
          </label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={3}
            placeholder="e.g. What risks does the company disclose about export controls?"
            className="block w-full rounded-md border border-neutral-300 bg-white p-3 text-sm shadow-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 dark:border-neutral-700 dark:bg-neutral-900"
          />
          <div className="mt-2 flex flex-wrap gap-2">
            {SAMPLE_QUESTIONS[ticker].map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => setQuestion(q)}
                className="rounded-full border border-neutral-300 px-2 py-0.5 text-xs text-neutral-600 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
              >
                {q.length > 60 ? q.slice(0, 60) + "…" : q}
              </button>
            ))}
          </div>
        </div>

        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "Researching…" : "Ask"}
        </button>
      </form>

      {error && (
        <div className="mt-6 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
          {error}
        </div>
      )}

      {result && <AnswerView result={result} />}
    </main>
  );
}
