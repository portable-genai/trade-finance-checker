"use client";

import { useEffect, useState } from "react";

import { watchAnswers } from "../lib/answer-provenance.mjs";
import { API_BASE, health } from "../lib/api";

/**
 * Two small pills at the top right of every page: the model that ANSWERED, and `Search` when
 * the answer used an online search tool (owner decision, 2026-09-23; they replace the
 * full-width provenance banner).
 *
 * The pill names what answered, not what configuration would call. Until an answer arrives it
 * shows the service's configured `generator_model` from `/healthz`, dimmed, with where the
 * runtime sits in its title. From then on it shows the `X-Answered-By` header of the console's
 * last answering response, solid, and `Search` appears only while that response carried
 * `X-Search-Used: true`. Both headers are emitted by the service (`install_answer_provenance`
 * in `api/app.py`), which also exposes them to this console's cross-origin reads.
 *
 * **Every value comes from the service**, and nothing here infers one. The health call and the
 * wrapper both use the API base `lib/api` resolves, the one every other call in this console
 * already reaches, so `connect-src` and the service's CORS allowlist cover them.
 */

interface Configured {
  model: string;
  where: string;
}

interface Answer {
  model: string;
  search: boolean;
}

const PILL = "max-w-[260px] truncate rounded-full border px-2.5 py-px text-[11px] leading-[1.6]";

/**
 * Renders once the service has answered `/healthz`, and nothing before that.
 *
 * The null-until-known state is deliberate: a pill defaulting to a model or a runtime while the
 * fetch is in flight would state a falsehood on some page load, and a failed health call renders
 * nothing for the same reason. The page's own error surface owns the failure.
 */
export function ModelPills() {
  const [configured, setConfigured] = useState<Configured | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);

  useEffect(() => {
    let live = true;
    const stop = watchAnswers(window, API_BASE, (next) => {
      if (live) setAnswer(next);
    });
    health()
      .then((status) => {
        if (!live || !status?.runtime) return;
        setConfigured({
          model: String(status.generator_model ?? ""),
          where: status.runtime === "gcp" ? "running on GCP" : "running locally",
        });
      })
      .catch(() => undefined);
    return () => {
      live = false;
      stop();
    };
  }, []);

  if (!configured) return null;
  return (
    <div
      className="pointer-events-none fixed right-2.5 top-1.5 z-50 flex max-w-[calc(100vw-20px)] gap-1.5"
      data-testid="model-pills"
    >
      {answer ? (
        <span
          className={`${PILL} pointer-events-auto border-ink-900 bg-ink-900 text-white`}
          data-state="answered"
          title="answered the last request"
        >
          {answer.model}
        </span>
      ) : (
        <span
          className={`${PILL} pointer-events-auto border-dashed border-ink-300 bg-white text-ink-500`}
          data-state="configured"
          title={configured.where}
        >
          {configured.model}
        </span>
      )}
      {answer?.search ? (
        <span
          className={`${PILL} pointer-events-auto border-emerald-700 bg-emerald-700 text-white`}
          data-state="search"
          title="the last answer used an online search tool"
        >
          Search
        </span>
      ) : null}
    </div>
  );
}
