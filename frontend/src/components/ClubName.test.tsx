import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ClubName } from "./ClubName";

/** The rendered text, reassembled across the element boundary the accent
 *  introduces. Splitting the name into nodes is exactly what this component
 *  does, so every assertion about the *text* has to look at the whole subtree. */
function textOf(container: HTMLElement): string {
  return container.textContent ?? "";
}

describe("ClubName", () => {
  it("accents the second word", () => {
    const { container } = render(<ClubName name="Late Summer Feels" />);

    const accented = container.querySelector(".text-accent");
    expect(accented).not.toBeNull();
    expect(accented!.textContent).toBe("Summer");
  });

  it("leaves a single-word name entirely plain", () => {
    const { container } = render(<ClubName name="Mixtape" />);

    expect(container.querySelector(".text-accent")).toBeNull();
    expect(textOf(container)).toBe("Mixtape");
  });

  it("accents only the second word, not the tail", () => {
    const { container } = render(<ClubName name="One Two Three Four" />);

    expect(container.querySelectorAll(".text-accent")).toHaveLength(1);
    expect(container.querySelector(".text-accent")!.textContent).toBe("Two");
    expect(textOf(container)).toBe("One Two Three Four");
  });

  it("preserves the original whitespace rather than normalising it", () => {
    // The name is user input. Rendering it back with different spacing would be
    // a silent edit, so the split keeps its separators.
    const { container } = render(<ClubName name="  Odd   Spacing  Here " />);

    expect(textOf(container)).toBe("  Odd   Spacing  Here ");
    expect(container.querySelector(".text-accent")!.textContent).toBe("Spacing");
  });

  it("does not change the accessible name of the heading it sits in", () => {
    // The whole point of the split is that it is presentational. A screen reader
    // must still announce one club name, and every test and query that looks the
    // club up by name must keep working.
    render(
      <h2>
        <ClubName name="Late Summer Feels" />
      </h2>,
    );

    expect(screen.getByRole("heading", { name: "Late Summer Feels" })).toBeInTheDocument();
  });

  it("handles an empty name without inventing markup", () => {
    const { container } = render(<ClubName name="" />);

    expect(container.querySelector(".text-accent")).toBeNull();
    expect(textOf(container)).toBe("");
  });
});
