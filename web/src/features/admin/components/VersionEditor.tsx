'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Textarea } from '@/components/ui/Textarea';
import { ConceptListEditor } from '@/features/admin/components/ConceptListEditor';
import { ApiError } from '@/lib/api/client';
import {
  createVersion,
  publishVersion,
  updateVersion,
  type ConceptEntry,
  type QuestionVersion,
  type RubricValidation,
  type VersionContentInput,
} from '@/lib/api/admin';

export interface VersionEditorProps {
  questionId: string;
  /** The version being edited, or null when authoring a new one. */
  version: QuestionVersion | null;
}

type Mode = 'idle' | 'saving' | 'publishing';

const EMPTY: VersionContentInput = {
  prompt: '',
  ideal_answer: '',
  expected_concepts: [],
  common_mistakes: [],
  rubric: {},
};

/**
 * Author or edit a question's grading content.
 *
 * A published or superseded version renders read-only with an explanation, because the API
 * refuses to edit one and a form that silently fails on submit is worse than no form. The
 * "Save as new version" action is always available from that read-only state, which is the
 * correct way to change a rubric: the old version stays intact so past grades keep their meaning.
 *
 * Validation failures come back from the API as a structured list and are rendered as such,
 * rather than being flattened into one message. An author fixing a rubric needs the whole list.
 */
export function VersionEditor({ questionId, version }: VersionEditorProps) {
  const router = useRouter();
  const frozen = version !== null && version.status !== 'draft';

  const [content, setContent] = useState<VersionContentInput>(
    version
      ? {
          prompt: version.prompt,
          ideal_answer: version.ideal_answer,
          expected_concepts: version.expected_concepts,
          common_mistakes: version.common_mistakes,
          rubric: version.rubric,
        }
      : EMPTY,
  );
  const [rubricText, setRubricText] = useState(() =>
    JSON.stringify(version?.rubric ?? {}, null, 2),
  );
  const [rubricError, setRubricError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>('idle');
  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<RubricValidation | null>(null);
  const [saved, setSaved] = useState(false);

  const busy = mode !== 'idle';
  const incomplete = content.prompt.trim() === '' || content.ideal_answer.trim() === '';

  function set<K extends keyof VersionContentInput>(key: K, value: VersionContentInput[K]) {
    setContent((current) => ({ ...current, [key]: value }));
    setSaved(false);
    setValidation(null);
  }

  /** Parse the rubric JSON, keeping the raw text so an author's work is never discarded. */
  function readRubric(): Record<string, unknown> | null {
    const text = rubricText.trim();
    if (text === '') return {};
    try {
      const parsed: unknown = JSON.parse(text);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setRubricError('The rubric must be a JSON object.');
        return null;
      }
      setRubricError(null);
      return parsed as Record<string, unknown>;
    } catch {
      setRubricError('This is not valid JSON.');
      return null;
    }
  }

  /**
   * Turn an API failure into something an author can act on.
   *
   * A 422 from the publish gate carries the structured validation result, which is far more
   * useful rendered as a list than collapsed into a sentence.
   */
  function handleFailure(caught: unknown) {
    if (caught instanceof ApiError) {
      const { detail } = caught;
      if (
        typeof detail === 'object' &&
        detail !== null &&
        Array.isArray((detail as { errors?: unknown }).errors)
      ) {
        const structured = detail as RubricValidation;
        setValidation({
          is_valid: false,
          errors: structured.errors,
          warnings: structured.warnings ?? [],
        });
        return;
      }
      setError(caught.message);
      return;
    }
    setError('Something went wrong. Please try again.');
  }

  async function submit(event: FormEvent<HTMLFormElement>, publish: boolean) {
    event.preventDefault();
    setError(null);
    setValidation(null);
    setSaved(false);

    const rubric = readRubric();
    if (rubric === null) return;

    setMode(publish ? 'publishing' : 'saving');
    try {
      const payload = { ...content, rubric };
      if (version && !frozen) {
        const updated = await updateVersion(questionId, version.id, payload);
        if (publish) {
          await publishVersion(questionId, updated.id);
        }
      } else {
        await createVersion(questionId, { ...payload, publish });
      }
      setSaved(true);
      router.refresh();
    } catch (caught) {
      handleFailure(caught);
    } finally {
      setMode('idle');
    }
  }

  return (
    <section
      aria-labelledby="version-editor-heading"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="version-editor-heading" className="label-micro">
          {version ? `Version ${version.version}` : 'New version'}
        </h2>
        {frozen ? (
          <p className="text-xs text-text-muted">
            Read-only. Save as a new version to change the rubric.
          </p>
        ) : null}
      </header>

      {frozen ? (
        <div className="mt-4">
          <Alert tone="info">
            This version is {version.status} and cannot be edited. Attempts graded against it point
            at this exact rubric, so changing it would alter what a past score meant. Edit below
            and save as a new version instead — this one stays intact.
          </Alert>
        </div>
      ) : null}

      <form onSubmit={(event) => submit(event, false)} className="mt-5 space-y-6" noValidate>
        {saved ? <Alert tone="success">Saved.</Alert> : null}
        {error ? <Alert tone="error">{error}</Alert> : null}

        {validation ? (
          <Alert tone="error">
            <p className="font-medium">This version is not complete enough to publish.</p>
            <ul className="mt-2 list-inside list-disc space-y-1">
              {validation.errors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </Alert>
        ) : null}

        {validation && validation.warnings.length > 0 ? (
          <Alert tone="info">
            <p className="font-medium">Quality suggestions</p>
            <ul className="mt-2 list-inside list-disc space-y-1">
              {validation.warnings.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </Alert>
        ) : null}

        <Field
          id="version-prompt"
          label="Prompt"
          hint="The question exactly as a student will read it."
        >
          <Textarea
            id="version-prompt"
            rows={3}
            maxLength={4000}
            value={content.prompt}
            onChange={(event) => set('prompt', event.target.value)}
            disabled={busy}
          />
        </Field>

        <Field
          id="version-ideal"
          label="Ideal answer"
          hint="The reference the grader compares against. A thin reference marks down thorough answers, so cover the detail a strong candidate would give."
        >
          <Textarea
            id="version-ideal"
            rows={8}
            maxLength={8000}
            value={content.ideal_answer}
            onChange={(event) => set('ideal_answer', event.target.value)}
            disabled={busy}
          />
        </Field>

        <ConceptListEditor
          id="expected-concepts"
          label="Expected concepts"
          hint="What a complete answer demonstrates. Keys are recorded against every attempt and drive mastery, so keep them stable once published."
          entries={content.expected_concepts}
          onChange={(entries: ConceptEntry[]) => set('expected_concepts', entries)}
          disabled={busy}
        />

        <ConceptListEditor
          id="common-mistakes"
          label="Common mistakes"
          hint="Specific errors interviewers actually see. Naming them makes feedback concrete instead of generic."
          entries={content.common_mistakes}
          onChange={(entries: ConceptEntry[]) => set('common_mistakes', entries)}
          disabled={busy}
        />

        <Field
          id="version-rubric"
          label="Rubric"
          hint="Scoring guidance as a JSON object. Supports scoring_notes and band_thresholds."
          error={rubricError}
        >
          <Textarea
            id="version-rubric"
            mono
            rows={8}
            value={rubricText}
            invalid={rubricError !== null}
            onChange={(event) => {
              setRubricText(event.target.value);
              setRubricError(null);
              setValidation(null);
            }}
            disabled={busy}
          />
        </Field>

        <div className="flex flex-wrap gap-3 border-t border-border-subtle pt-5">
          <Button type="submit" variant="secondary" loading={mode === 'saving'} disabled={busy}>
            {version && !frozen ? 'Save draft' : 'Save as new version'}
          </Button>
          <Button
            type="button"
            loading={mode === 'publishing'}
            disabled={busy || incomplete}
            onClick={(event) =>
              submit(
                event as unknown as FormEvent<HTMLFormElement>,
                true,
              )
            }
          >
            Publish
          </Button>
        </div>
        {incomplete ? (
          <p className="text-xs text-text-muted">
            A prompt and an ideal answer are required before this can be published.
          </p>
        ) : null}
      </form>
    </section>
  );
}
