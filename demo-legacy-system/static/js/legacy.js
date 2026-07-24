// レガシーシステム自体には AI 機能は一切ない。素の fetch + DOM 操作のみ。
async function loadCustomers() {
    const res = await fetch("/legacy-api/customers");
    const rows = await res.json();
    const tbody = document.getElementById("customerRows");
    tbody.innerHTML = "";
    for (const c of rows) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${c.id}</td>
            <td>${c.name}</td>
            <td>${c.company}</td>
            <td>${c.phone}</td>
            <td>${c.status}</td>
        `;
        tbody.appendChild(tr);
    }
}

async function loadOrders() {
    const res = await fetch("/legacy-api/orders");
    const rows = await res.json();
    const tbody = document.getElementById("orderRows");
    tbody.innerHTML = "";
    for (const o of rows) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${o.id}</td>
            <td>${o.customer_name}</td>
            <td>${o.item}</td>
            <td>${o.qty}</td>
            <td>&yen;${o.amount.toLocaleString()}</td>
            <td>${o.date}</td>
        `;
        tbody.appendChild(tr);
    }
}
