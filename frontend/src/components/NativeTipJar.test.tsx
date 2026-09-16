import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NativeTipJar } from "./NativeTipJar";
import { tips } from "../ios/tips";

vi.mock("../ios/tips", async () => {
  const actual = await vi.importActual<typeof import("../ios/tips")>("../ios/tips");
  return {
    ...actual,
    tips: { ...actual.tips, getProducts: vi.fn(), purchase: vi.fn() },
  };
});

const mockGetProducts = vi.mocked(tips.getProducts);
const mockPurchase = vi.mocked(tips.purchase);

const PRODUCTS = [
  { id: "com.mysterymixclub.app.tip.small", displayName: "small tip", displayPrice: "$1.99" },
  { id: "com.mysterymixclub.app.tip.medium", displayName: "medium tip", displayPrice: "$4.99" },
  { id: "com.mysterymixclub.app.tip.large", displayName: "large tip", displayPrice: "$9.99" },
];

describe("NativeTipJar (MysteryMixClub-4vii.15)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing while products are loading", () => {
    mockGetProducts.mockReturnValue(new Promise(() => {}));
    const { container } = render(<NativeTipJar />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing if products fail to load (fails quietly)", async () => {
    mockGetProducts.mockRejectedValue(new Error("boom"));
    const { container } = render(<NativeTipJar />);
    await vi.waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders a button per tip option with its real localized price, plus the no-unlock disclosure", async () => {
    mockGetProducts.mockResolvedValue({ products: PRODUCTS });
    render(<NativeTipJar />);

    expect(await screen.findByRole("button", { name: /small tip.*\$1\.99/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /medium tip.*\$4\.99/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /large tip.*\$9\.99/ })).toBeInTheDocument();
    expect(screen.getByText(/don't unlock any features/i)).toBeInTheDocument();
  });

  it("purchasing successfully shows a thank-you, not an error", async () => {
    const user = userEvent.setup();
    mockGetProducts.mockResolvedValue({ products: PRODUCTS });
    mockPurchase.mockResolvedValue({ status: "success" });
    render(<NativeTipJar />);

    await user.click(await screen.findByRole("button", { name: /small tip/ }));

    expect(mockPurchase).toHaveBeenCalledWith({ productId: "com.mysterymixclub.app.tip.small" });
    expect(await screen.findByRole("status")).toHaveTextContent(/thank you/i);
  });

  it("a cancelled purchase shows neither a thank-you nor an error", async () => {
    const user = userEvent.setup();
    mockGetProducts.mockResolvedValue({ products: PRODUCTS });
    mockPurchase.mockResolvedValue({ status: "cancelled" });
    render(<NativeTipJar />);

    await user.click(await screen.findByRole("button", { name: /small tip/ }));

    await vi.waitFor(() => expect(mockPurchase).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a calm error message if the purchase call rejects", async () => {
    const user = userEvent.setup();
    mockGetProducts.mockResolvedValue({ products: PRODUCTS });
    mockPurchase.mockRejectedValue({ code: "PURCHASE_FAILED" });
    render(<NativeTipJar />);

    await user.click(await screen.findByRole("button", { name: /small tip/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't go through/i);
  });
});
