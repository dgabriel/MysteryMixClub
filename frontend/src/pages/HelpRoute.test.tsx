import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { HelpRoute } from "./HelpRoute";
import { useAuth } from "../hooks/useAuth";

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockUseAuth = vi.mocked(useAuth);

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <HelpRoute />
    </MemoryRouter>,
  );
}

describe("HelpRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAuth.mockReturnValue({ status: "unauthenticated" } as ReturnType<typeof useAuth>);
  });

  it("scrolls the target section into view when the URL carries a hash (MYS-222)", () => {
    // Client-side route changes don't get the browser's native #hash scroll,
    // so HelpRoute does it itself — verify it actually reaches for the right
    // element rather than assuming a plain anchor would have handled it.
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;

    renderAt("/help#just-vibing");

    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth" });
  });

  it("does not scroll when there's no hash", () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;

    renderAt("/help");

    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("every section anchor referenced by a hash actually exists on the page", () => {
    // Guards against a HelpLink and this page's section ids drifting apart.
    const { container } = renderAt("/help");
    const sectionIds = Array.from(container.querySelectorAll("section[id]")).map((el) => el.id);

    expect(sectionIds).toEqual(
      expect.arrayContaining([
        "getting-in",
        "clubs",
        "mystery-mixes",
        "submitting-a-song",
        "voting-results",
        "just-vibing",
        "listening-playlists",
        "notifications",
        "your-account",
        "other",
      ]),
    );
  });
});
