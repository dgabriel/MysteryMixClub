import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ContactEmail } from "./ContactEmail";

describe("ContactEmail", () => {
  it("shows the label, not the address, before it's clicked", () => {
    render(<ContactEmail user="info" domain="mysterymixclub.com" label="email us" />);

    expect(screen.getByRole("button", { name: /^email us$/i })).toBeInTheDocument();
    expect(screen.queryByText(/info@mysterymixclub\.com/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("reveals the mailto link only after a click", async () => {
    const user = userEvent.setup();
    render(<ContactEmail user="info" domain="mysterymixclub.com" label="email us" />);

    await user.click(screen.getByRole("button", { name: /^email us$/i }));

    const link = screen.getByRole("link", { name: /info@mysterymixclub\.com/i });
    expect(link).toHaveAttribute("href", "mailto:info@mysterymixclub.com");
    expect(screen.queryByRole("button", { name: /^email us$/i })).not.toBeInTheDocument();
  });

  it("defaults the label to 'email us' when none is given", () => {
    render(<ContactEmail user="info" domain="mysterymixclub.com" />);
    expect(screen.getByRole("button", { name: /^email us$/i })).toBeInTheDocument();
  });
});
