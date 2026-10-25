import { useState } from "react";
import { api, ApiError } from "../api/client";
import { CandidateAvatar, formatCount } from "./resultShared";
import type { CorpusKind, CreatorSnapshot, LookalikeResponse, ProspectSnapshot } from "../types";

export function MoreLikeThis({ kind, candidateId }: { kind: CorpusKind; candidateId: number }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<LookalikeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (loading) return;
    setOpen((current) => !current);
    if (open || result) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.findLookalikes(kind, candidateId));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not find similar profiles.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="lookalike-tool">
      <button className="btn btn-secondary" type="button" aria-expanded={open} onClick={() => void load()}>
        {loading ? "Finding similar..." : open ? "Hide similar profiles" : "More like this"}
      </button>
      {open && (
        <div className="lookalike-results">
          <div className="lookalike-heading">
            <h3>Similar profiles</h3>
            <span>Content similarity, not fit</span>
          </div>
          {error && <p className="lookalike-error" role="alert">{error}</p>}
          {loading && <p className="lookalike-state" role="status">Searching the indexed profiles...</p>}
          {result && result.candidates.length === 0 && (
            <p className="lookalike-state">No similar profiles are available in this index.</p>
          )}
          {result && result.candidates.length > 0 && (
            <ol className="lookalike-list">
              {result.candidates.map((candidate) => (
                <LookalikeRow key={candidate.id} kind={kind} candidate={candidate} />
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}

function LookalikeRow({ kind, candidate }: { kind: CorpusKind; candidate: CreatorSnapshot | ProspectSnapshot }) {
  const creator = kind === "creator" ? candidate as CreatorSnapshot : null;
  const company = kind === "prospect" ? candidate as ProspectSnapshot : null;
  const name = creator ? creator.name || creator.handle : company!.name;
  const subtitle = creator
    ? [creator.handle, creator.platform, creator.city].filter(Boolean).join(" · ")
    : [company!.industry, company!.city, company!.country].filter(Boolean).join(" · ");
  const details = creator
    ? `${formatCount(creator.followers)} followers · ${creator.engagement_pct.toFixed(1)}% engagement`
    : `${formatCount(company!.headcount)} employees · ${company!.funding_stage || "Company"}`;

  return (
    <li className="lookalike-row">
      <CandidateAvatar name={name} kind={kind} />
      <div className="lookalike-copy">
        <strong>{name}</strong>
        <span>{subtitle}</span>
        <small>{details}</small>
      </div>
      <span className="lookalike-score">
        {candidate.similarity === null ? "—" : `${(candidate.similarity * 100).toFixed(1)}%`}
      </span>
    </li>
  );
}
