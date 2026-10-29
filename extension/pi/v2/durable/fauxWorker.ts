// The production faux worker (docs/design/pi-durable-v2-foundations.md §12 the fixture-review
// execution kind, §11 the door): the deterministic model catalog the door composes the fixture
// program with, so a shell-driven execution runs without a real provider (§14 defers that).
//
// Invariants:
// - Deterministic: every attempt makes at most two model requests — one `report` call over the
//   subject tree named by the worker prompt, then a final `done` text once a tool result exists.
// - Answers come from the transcript alone, never from request order, so concurrent workers each
//   get their own answer whichever request the provider serves first.
// - The queue never runs dry: each step appends its own replacement before it answers. The faux
//   provider shifts a step synchronously per request and invokes it in a microtask, so the initial
//   depth covers requests shifted before any step has run.
// - A transcript that is not a fixture worker's gets a provider error, never a report.

import type { AssistantMessage, Message, Models, UserMessage } from "@earendil-works/pi-ai";
import { createModels } from "@earendil-works/pi-ai/models";
import {
  type FauxResponseStep,
  fauxAssistantMessage,
  fauxProvider,
  fauxText,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { FIXTURE_MODEL, FIXTURE_REPORT_TOOL, fixtureWorkerPrompt } from "../kernel/fixture.ts";

/** The summary every faux report carries. */
export const FIXTURE_WORKER_SUMMARY = "fixture review: no findings";

/**
 * How many self-replenishing steps stay queued: the most requests that may be in flight at once
 * (the fixture runs two workers, each with one request at a time).
 */
export const FIXTURE_WORKER_QUEUE_DEPTH = 16;

const PROMPT_PATTERN = /^Review subject (\S+) as reviewer (\S+)\.$/;

function contentText(content: UserMessage["content"]): string {
  if (typeof content === "string") return content;
  return content.map((part) => (part.type === "text" ? part.text : "")).join("");
}

/** The subject tree a fixture worker prompt names, or `null` when `text` is not one. */
function promptTarget(text: string): string | null {
  const match = PROMPT_PATTERN.exec(text);
  if (match === null) return null;
  const [, tree, role] = match;
  if (tree === undefined || role === undefined) return null;
  try {
    return fixtureWorkerPrompt(role, tree) === text ? tree : null;
  } catch (error) {
    if (error instanceof RangeError) return null;
    throw error;
  }
}

/**
 * The faux worker's answer to a transcript: an error unless its first user message is a fixture
 * worker prompt; `done` once a tool result exists; otherwise one `report` call over the prompt's
 * tree with no findings.
 */
export function fixtureWorkerResponse(messages: readonly Message[]): AssistantMessage {
  const first = messages.find((message): message is UserMessage => message.role === "user");
  const tree = first === undefined ? null : promptTarget(contentText(first.content));
  if (tree === null) {
    return fauxAssistantMessage([], {
      stopReason: "error",
      errorMessage: "not a fixture worker prompt",
    });
  }
  if (messages.some((message) => message.role === "toolResult")) {
    return fauxAssistantMessage([fauxText("done")]);
  }
  return fauxAssistantMessage(
    [
      fauxToolCall(
        FIXTURE_REPORT_TOOL,
        { subjectDigest: tree, summary: FIXTURE_WORKER_SUMMARY, findings: [] },
        { id: "report-1" },
      ),
    ],
    { stopReason: "toolUse" },
  );
}

/**
 * A model catalog whose faux provider serves `FIXTURE_MODEL` with `fixtureWorkerResponse`, forever.
 * Throws when the faux provider does not serve the fixture model.
 */
export function fixtureWorkerModels(): Models {
  const faux = fauxProvider();
  const models = createModels();
  models.setProvider(faux.provider);
  if (faux.getModel(FIXTURE_MODEL.modelId) === undefined) {
    throw new Error(`the faux provider does not serve ${FIXTURE_MODEL.modelId}`);
  }
  const step: FauxResponseStep = (transcript) => {
    faux.appendResponses([step]);
    return fixtureWorkerResponse(transcript.messages);
  };
  faux.setResponses(Array.from({ length: FIXTURE_WORKER_QUEUE_DEPTH }, () => step));
  return models;
}
