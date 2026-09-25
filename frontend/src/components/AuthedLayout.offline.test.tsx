import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AuthedLayout } from "./AuthedLayout";
import { useAuth } from "../hooks/useAuth";
import {
  RECONNECTED_MS,
  reportNetworkFailure,
  reportNetworkSuccess,
  resetConnectivityForTests,
} from "../lib/connectivity";
import { forgetTypedFields } from "../lib/offline";

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));
vi.mock("../data/releaseNotes", () => ({
  hasUnseenRelease: () => false,
  markLatestReleaseSeen: vi.fn(),
}));

let mounts = 0;

/** A page that counts its mounts (a remount is a data reload) and has a field. */
function Page() {
  const [draft, setDraft] = useState("");
  useEffect(() => {
    mounts += 1;
  }, []);
  return (
    <main>
      <p>page content</p>
      <label>
        note
        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} />
      </label>
    </main>
  );
}

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/home"]}>
      <Routes>
        <Route element={<AuthedLayout />}>
          <Route path="/home" element={<Page />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthedLayout offline state (MysteryMixClub-ga4y)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    resetConnectivityForTests();
    forgetTypedFields();
    mounts = 0;
    vi.mocked(useAuth).mockReturnValue({
      status: "authenticated",
      isAuthenticated: true,
      displayName: "Ada",
      userId: "user-1",
      isPlatformAdmin: false,
      logout: vi.fn(),
      logoutAll: vi.fn(),
    } as unknown as ReturnType<typeof useAuth>);
  });

  afterEach(() => {
    resetConnectivityForTests();
    vi.useRealTimers();
  });

  it("offline replaces the page with the offline screen, keeping the page mounted", () => {
    renderLayout();
    expect(mounts).toBe(1);

    act(() => reportNetworkFailure());

    expect(screen.getByRole("heading", { name: /you're offline/i })).toBeInTheDocument();
    // jsdom has no Tailwind CSS, so assert the class that hides it.
    expect(document.getElementById("main-content")).toHaveClass("hidden");
    expect(screen.getByText("page content")).toBeInTheDocument();
    expect(mounts).toBe(1);
  });

  it("back online: shows 'back online', then reloads the page", () => {
    renderLayout();
    act(() => reportNetworkFailure());

    act(() => reportNetworkSuccess());
    expect(screen.getByRole("heading", { name: /back online/i })).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(RECONNECTED_MS);
    });
    expect(screen.queryByRole("heading", { name: /back online/i })).not.toBeInTheDocument();
    expect(document.getElementById("main-content")).not.toHaveClass("hidden");
    expect(mounts).toBe(2);
  });

  it("back online with unsaved typing: the page and the draft are left as they were", () => {
    renderLayout();
    fireEvent.input(screen.getByLabelText("note"), { target: { value: "half a thought" } });
    act(() => reportNetworkFailure());

    act(() => reportNetworkSuccess());
    act(() => {
      vi.advanceTimersByTime(RECONNECTED_MS);
    });

    expect(mounts).toBe(1);
    expect(screen.getByLabelText("note")).toHaveValue("half a thought");
    expect(document.getElementById("main-content")).not.toHaveClass("hidden");
  });
});
