interface Product {
  id: string;
  name: string;
  price: number;
}

async function loadProducts(): Promise<void> {
  const list = document.querySelector<HTMLUListElement>("#products");
  if (!list) return;

  const response = await fetch("/api/products");
  const body = (await response.json()) as { products: Product[] };

  for (const product of body.products) {
    const item = document.createElement("li");
    item.dataset.productId = product.id;
    item.textContent = `${product.name} — ${(product.price / 100).toFixed(2)}`;
    list.append(item);
  }
}

document
  .querySelector<HTMLButtonElement>("[data-testid=remove-item]")
  ?.addEventListener("click", () => {
    // The fixture's unlabeled button intentionally does nothing useful.
    document.body.dataset.lastAction = "remove";
  });

void loadProducts();
