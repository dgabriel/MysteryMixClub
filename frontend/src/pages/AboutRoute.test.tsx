import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { useAuth } from "../hooks/useAuth";

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockUseAuth = vi.mocked(useAuth);

async function renderAbout({ native }: { native: boolean }) {
  vi.resetModules();
  vi.doMock("../lib/platform", () => ({ IS_NATIVE_BUILD: native }));
  const { AboutRoute } = await import("./AboutRoute");
  return render(
    <MemoryRouter>
      <AboutRoute />
    </MemoryRouter>,
  );
}

describe("AboutRoute", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ status: "unauthenticated" } as ReturnType<typeof useAuth>);
  });

  afterEach(() => {
    vi.doUnmock("../lib/platform");
    vi.resetModules();
  });

  it("on the web, asks for tips and links to venmo", async () => {
    await renderAbout({ native: false });

    expect(screen.getByRole("link", { name: /tip me on venmo/i })).toBeInTheDocument();
    expect(screen.getByText(/you can tip me on venmo/i)).toBeInTheDocument();
  });

  it("in the iPhone app, neither asks for tips nor links anywhere to pay (4vii.50, Guideline 3.1.1)", async () => {
    await renderAbout({ native: true });

    expect(screen.queryByRole("link", { name: /tip/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/tip me/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/venmo/i)).not.toBeInTheDocument();
  });

  it("quotes no dollar amounts that can go stale", async () => {
    const { container } = await renderAbout({ native: false });

    expect(container.textContent).not.toMatch(/\$\d/);
  });
});
