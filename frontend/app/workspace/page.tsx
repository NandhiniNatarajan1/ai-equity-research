"use client";

import { Download, FileBarChart, Loader2, Send, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { TopBar } from "@/components/shell/TopBar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { AgentIntelligencePanel } from "@/components/workspace/AgentIntelligencePanel";
import { FilingStatusCard } from "@/components/workspace/FilingStatusCard";
import { AnswerBubble, QuestionBubble } from "@/components/workspace/MessageBubble";
import { TickerSearch } from "@/components/workspace/TickerSearch";
import type { AskResponse, SystemCompany } from "@/lib/api";
import { askResearch, getSystemStatus } from "@/lib/api";

type Turn =
  | { kind: "question"; ticker: string; question: string }
  | { kind: "answer"; result: AskResponse }
  | { kind: "error"; message: string };

const SUGGESTIONS: { label: string; q: string }[] = [
  {
    label: "Export controls risk",
    q: "What risks does the company disclose from U.S. export controls affecting sales to China?",
  },
  {
    label: "Revenue growth + margin",
    q: "What was revenue growth and gross margin in the most recent fiscal year?",
  },
  {
    label: "AI accelerator strategy",
    q: "How does the company describe its strategy for AI accelerators?",
  },
  {
    label: "Supply chain concentration",
    q: "How concentrated is the supply chain for advanced chip manufacturing?",
  },
];

export default function WorkspacePage() {
  const [ticker, setTicker] = useState<string>("NVDA");
  const [companies, setCompanies] = useState<SystemCompany[]>([]);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [latestResult, setLatestResult] = useState<AskResponse | null>(null);
  const [latestError, setLatestError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getSystemStatus()
      .then((s) => setCompanies(s.companies))
      .catch(() => {});
  }, []);

  const company = useMemo(
    () => companies.find((c) => c.ticker === ticker) ?? null,
    [companies, ticker],
  );

  const lastTurn = turns[turns.length - 1];
  const phase: "idle" | "routing" | "running" | "done" | "error" = loading
    ? lastTurn && lastTurn.kind === "question"
      ? "running"
      : "routing"
    : latestError
    ? "error"
    : latestResult
    ? "done"
    : "idle";

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, loading]);

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    const q = question.trim();
    if (!q || loading) return;
    setLoading(true);
    setLatestError(null);
    setLatestResult(null);
    setStartedAt(Date.now());
    setTurns((t) => [...t, { kind: "question", ticker, question: q }]);
    setQuestion("");
    try {
      const r = await askResearch(ticker, q);
      setLatestResult(r);
      setTurns((t) => [...t, { kind: "answer", result: r }]);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setLatestError(message);
      setTurns((t) => [...t, { kind: "error", message }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <TopBar
        title="Research Workspace"
        subtitle="Ask about the company's business, risks, or financials. Every answer is backed by passages from its latest annual report."
      />

      {/* Ticker row */}
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface/40 px-5 py-3">
        <TickerSearch value={ticker} onChange={setTicker} />
        <div className="flex-1 min-w-[320px]">
          <FilingStatusCard company={company} />
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => window.open(`http://localhost:8000/research/report/${ticker}.html`, "_blank")}
          title="Opens the full research report in a new tab · first call ~60s, then cached"
        >
          <FileBarChart className="size-3.5" />
          Open report
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => window.open(`http://localhost:8000/research/report/${ticker}/pdf`, "_blank")}
          title="Download the report as a PDF (WeasyPrint)"
        >
          <Download className="size-3.5" />
          PDF
        </Button>
      </div>

      {/* Split-panel body */}
      <div className="flex flex-1 min-h-0">
        {/* Conversation */}
        <section className="flex min-w-0 flex-1 flex-col">
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
            {turns.length === 0 && <EmptyState onPick={(q) => setQuestion(q)} />}
            <div className="mx-auto flex max-w-3xl flex-col gap-6">
              {turns.map((t, i) =>
                t.kind === "question" ? (
                  <QuestionBubble key={i} ticker={t.ticker} question={t.question} />
                ) : t.kind === "answer" ? (
                  <AnswerBubble key={i} result={t.result} />
                ) : (
                  <div
                    key={i}
                    className="rounded-md border border-neg/40 bg-neg/10 p-3 text-xs text-neg"
                  >
                    {t.message}
                  </div>
                ),
              )}
              {loading && (
                <div className="flex items-center gap-2 text-xs text-mutedFg">
                  <Loader2 className="size-3.5 animate-spin text-accent" />
                  Running agents on <span className="font-mono text-accent">{ticker}</span>…
                </div>
              )}
            </div>
          </div>

          {/* Composer */}
          <form
            onSubmit={submit}
            className="border-t border-border bg-surface/40 px-5 py-3"
          >
            <div className="mx-auto flex max-w-3xl flex-col gap-2">
              <div className="flex items-center gap-2 text-[11px] text-mutedFg">
                <Sparkles className="size-3" />
                Suggestions:
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s.label}
                    type="button"
                    onClick={() => setQuestion(s.q)}
                    className="rounded-full border border-border bg-surfaceAlt px-2 py-0.5 text-mutedFg hover:text-fg"
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <Textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder={`Ask about ${ticker}'s business, risks, competition, or financials…`}
                  rows={2}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault();
                      submit();
                    }
                  }}
                />
                <Button
                  type="submit"
                  disabled={loading || !question.trim()}
                  className="self-stretch px-5"
                >
                  {loading ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                  Ask
                </Button>
              </div>
              <div className="flex items-center justify-between text-[10px] text-mutedFg">
                <span>⌘/Ctrl + Enter to submit</span>
                <span>Every quoted passage comes from an actual SEC filing.</span>
              </div>
            </div>
          </form>
        </section>

        <Separator orientation="vertical" />

        {/* Research Intelligence */}
        <aside className="hidden xl:flex w-[360px] shrink-0 flex-col bg-surface/40">
          <AgentIntelligencePanel
            phase={phase}
            startedAt={startedAt}
            result={latestResult}
            error={latestError}
          />
        </aside>
      </div>
    </>
  );
}

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center justify-center gap-5 py-12 text-center animate-fade-in">
      <div className="flex size-10 items-center justify-center rounded-full bg-accent/15 text-accent">
        <Sparkles className="size-5" />
      </div>
      <div>
        <h2 className="text-base font-semibold">Ask a question about this company</h2>
        <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-mutedFg">
          This workspace reads a company&apos;s{" "}
          <span className="font-medium text-fg">annual report (10-K)</span> and answers questions
          about its{" "}
          <span className="font-medium text-fg">business, risks, or financials</span>. You&apos;ll
          get a short answer with the{" "}
          <span className="font-medium text-fg">exact passages</span> it came from.
        </p>
      </div>
      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.label}
            type="button"
            onClick={() => onPick(s.q)}
            className="rounded-md border border-border bg-surface px-3 py-2 text-left text-xs text-fg transition-colors hover:border-ring/40"
          >
            <div className="font-semibold">{s.label}</div>
            <div className="mt-0.5 text-mutedFg line-clamp-2">{s.q}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
