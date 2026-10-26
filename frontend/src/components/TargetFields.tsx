import type { CorpusKind } from "../types";

/** Reads one of the brief's structured fields.
 *
 *  The fields are declared on `Brief` with their own types, so the brief has no
 *  index signature and cannot be read dynamically without a cast. One cast in
 *  one place is better than widening `Brief` itself to an index signature,
 *  which would let any key be read off it anywhere.
 */
function read(values: object, field: string): unknown {
  return (values as Record<string, unknown>)[field];
}
import {
  AGE_BANDS, BUDGET_BANDS, GENDER_PREFERENCES, SIZE_BANDS, TARGET_HELP, parseSizeBand,
} from "../panels/targets";

/** The structured part of a brief: the requirements, as opposed to the wording.
 *
 *  Every field is optional and a brief with none of them filled in still works:
 *  the free text drives the embedding and the corpus's rubric judges the match.
 *  These exist for the case where the user knows the audience or the ICP
 *  precisely and wants it enforced rather than inferred.
 */
export function TargetFields({
  kind, values, onChange,
}: {
  kind: CorpusKind;
  values: object;
  onChange: (field: string, value: unknown) => void;
}) {
  const help = TARGET_HELP[kind];
  if (kind === "creator") {
    const ages = (read(values, "audience_age") as string[]) ?? [];
    return (
      <div className="target-fields">
        <div className="target-field">
          <span className="target-label">Audience age</span>
          <div className="target-chips" role="group" aria-label="Audience age bands">
            {AGE_BANDS.map((band) => {
              const on = ages.includes(band);
              return (
                <button
                  key={band}
                  type="button"
                  className={on ? "chip chip-on" : "chip"}
                  aria-pressed={on}
                  onClick={() => onChange(
                    "audience_age",
                    on ? ages.filter((a) => a !== band) : [...ages, band],
                  )}
                >
                  {band}
                </button>
              );
            })}
          </div>
          <p className="target-help">{help.audience_age}</p>
        </div>

        <label className="brief-field" htmlFor="audience-gender">
          <span>Audience gender <em>optional</em></span>
          <select
            id="audience-gender"
            value={(read(values, "audience_gender") as string) ?? ""}
            onChange={(event) => onChange("audience_gender", event.target.value)}
          >
            {GENDER_PREFERENCES.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <p className="target-help">{help.audience_gender}</p>
        </label>

        <label className="brief-field" htmlFor="audience-countries">
          <span>Audience countries <em>optional</em></span>
          <input
            id="audience-countries"
            value={((read(values, "audience_countries") as string[]) ?? []).join(", ")}
            placeholder="e.g. USA, UK, Germany"
            onChange={(event) => onChange(
              "audience_countries",
              event.target.value.split(",").map((c) => c.trim()).filter(Boolean),
            )}
          />
          <p className="target-help">{help.audience_countries}</p>
        </label>

        <label className="brief-field" htmlFor="audience-languages">
          <span>Content languages <em>optional</em></span>
          <input
            id="audience-languages"
            value={((read(values, "languages") as string[]) ?? []).join(", ")}
            placeholder="e.g. English, Spanish"
            onChange={(event) => onChange("languages", event.target.value.split(",").map((item) => item.trim()).filter(Boolean))}
          />
          <p className="target-help">{help.languages}</p>
        </label>

        <label className="brief-field" htmlFor="min-reach">
          <span>Minimum reach <em>optional</em></span>
          <input
            id="min-reach"
            type="number"
            min={0}
            max={100}
            step={5}
            value={Math.round(((read(values, "min_reach_ratio") as number) ?? 0) * 100)}
            onChange={(event) => onChange(
              "min_reach_ratio",
              Number(event.target.value) / 100,
            )}
          />
          <p className="target-help">{help.min_reach_ratio}</p>
        </label>
      </div>
    );
  }

  return (
    <div className="target-fields">
      <label className="brief-field" htmlFor="target-industries">
        <span>Industries <em>optional</em></span>
        <input
          id="target-industries"
          value={((read(values, "target_industries") as string[]) ?? []).join(", ")}
          placeholder="e.g. logistics, fintech"
          onChange={(event) => onChange(
            "target_industries",
            event.target.value.split(",").map((c) => c.trim()).filter(Boolean),
          )}
        />
        <p className="target-help">{help.target_industries}</p>
      </label>

      <label className="brief-field" htmlFor="target-size">
        <span>Company size <em>optional</em></span>
        <select
          id="target-size"
          value={sizeBandValue(read(values, "target_size"))}
          onChange={(event) => onChange("target_size", parseSizeBand(event.target.value))}
        >
          {sizeBandValue(read(values, "target_size")) && !SIZE_BANDS.some((option) => option.value === sizeBandValue(read(values, "target_size"))) && (
            <option value={sizeBandValue(read(values, "target_size"))}>{sizeBandValue(read(values, "target_size")).replace("-", "–")} staff (custom)</option>
          )}
          {SIZE_BANDS.map((band) => (
            <option key={band.value} value={band.value}>{band.label}</option>
          ))}
        </select>
        <p className="target-help">{help.target_size}</p>
      </label>

      <label className="brief-field" htmlFor="target-countries">
        <span>Countries <em>optional</em></span>
        <input
          id="target-countries"
          value={((read(values, "target_countries") as string[]) ?? []).join(", ")}
          placeholder="e.g. USA, UK, Germany"
          onChange={(event) => onChange(
            "target_countries",
            event.target.value.split(",").map((c) => c.trim()).filter(Boolean),
          )}
        />
        <p className="target-help">{help.target_countries}</p>
      </label>

      <label className="brief-field" htmlFor="budget-band">
        <span>Buyer budget <em>optional</em></span>
        <select
          id="budget-band"
          value={(read(values, "budget_band") as string) ?? ""}
          onChange={(event) => onChange("budget_band", event.target.value)}
        >
          {BUDGET_BANDS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <p className="target-help">{help.budget_band}</p>
      </label>

      <label className="brief-field" htmlFor="buyer-roles">
        <span>Buyer roles <em>optional</em></span>
        <input
          id="buyer-roles"
          value={((read(values, "buyer_roles") as string[]) ?? []).join(", ")}
          placeholder="e.g. operations, finance"
          onChange={(event) => onChange("buyer_roles", event.target.value.split(",").map((item) => item.trim()).filter(Boolean))}
        />
        <p className="target-help">{help.buyer_roles}</p>
      </label>
    </div>
  );
}

/** The select's value for a stored band, so the control shows what is set. */
function sizeBandValue(value: unknown): string {
  if (!Array.isArray(value) || value.length !== 2) return "";
  return `${value[0]}-${value[1]}`;
}
