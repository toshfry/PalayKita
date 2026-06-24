function peso(value) {
    const number = Number(value || 0);
    return "₱" + number.toLocaleString("en-PH", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

function setStatusBadge(element, status) {
    if (!element) return;
    element.textContent = status;
    element.classList.add("summary-badge");
    element.classList.remove("badge-paid", "badge-partial", "badge-unpaid");
    const key = String(status || "").toLowerCase();
    if (key === "paid") {
        element.classList.add("badge-paid");
    } else if (key === "partial") {
        element.classList.add("badge-partial");
    } else {
        element.classList.add("badge-unpaid");
    }
}

function computePreview() {
    const form = document.getElementById("transactionForm");
    if (!form) return;

    const transactionType = document.getElementById("transactionType")?.value || "local";
    if (transactionType === "commercial") {
        computeCommercialPreview();
        return;
    }

    const kilos = Number(document.getElementById("kilos")?.value || 0);
    const millingRate = Number(document.getElementById("millingRate")?.value || 0);
    const amountPaid = Number(document.getElementById("amountPaid")?.value || 0);
    const hasChaff = document.getElementById("hasChaff")?.value === "yes";
    const chaffKilos = Number(document.getElementById("chaffKilos")?.value || 0);
    const chaffRate = Number(document.getElementById("chaffRate")?.value || 0);

    const gross = kilos * millingRate;
    const chaffDeduction = hasChaff ? chaffKilos * chaffRate : 0;
    const net = gross - chaffDeduction;
    let balance = net - amountPaid;

    let status = "Paid";
    if (balance <= 0) {
        balance = 0;
        status = "Paid";
    } else if (amountPaid <= 0) {
        status = "Unpaid";
    } else {
        status = "Partial";
    }

    document.getElementById("grossPreview").textContent = peso(gross);
    document.getElementById("chaffPreview").textContent = peso(chaffDeduction);
    document.getElementById("netPreview").textContent = peso(net);
    document.getElementById("balancePreview").textContent = peso(balance);
    setStatusBadge(document.getElementById("statusPreview"), status);

    const customerName = form.querySelector("[name='customer_name']")?.value.trim();
    const warning = document.getElementById("nameWarning");

    if (warning) {
        if (balance > 0 && !customerName) {
            warning.classList.remove("hidden");
        } else {
            warning.classList.add("hidden");
        }
    }
}

function computeCommercialPreview() {
    const sacks = Number(document.getElementById("commercialSacks")?.value || 0);
    const price = Number(document.getElementById("commercialPrice")?.value || 0);
    const totalOverride = document.getElementById("commercialTotalAmount");
    const amountPaid = Number(document.getElementById("commercialAmountPaid")?.value || 0);

    const total = totalOverride ? Number(totalOverride.value || 0) : sacks * price;
    let balance = total - amountPaid;

    let status = "Paid";
    if (balance <= 0) {
        balance = 0;
        status = "Paid";
    } else if (amountPaid <= 0) {
        status = "Unpaid";
    } else {
        status = "Partial";
    }

    const grossPreview = document.getElementById("commercialGrossPreview");
    const netPreview = document.getElementById("commercialNetPreview");
    const balancePreview = document.getElementById("commercialBalancePreview");
    const statusPreview = document.getElementById("commercialStatusPreview");
    const statusField = document.getElementById("commercialPaymentStatus");

    if (grossPreview) grossPreview.textContent = peso(total);
    if (netPreview) netPreview.textContent = peso(total);
    if (balancePreview) balancePreview.textContent = peso(balance);
    setStatusBadge(statusPreview, status);
    if (statusField) statusField.value = status;
}

function setTransactionType(type) {
    const hidden = document.getElementById("transactionType");
    if (!hidden) return;

    const form = document.getElementById("transactionForm");
    const readonlyForm = form?.dataset.readonly === "true";
    hidden.value = type;
    if (form) {
        form.classList.toggle("txn-type-local", type === "local");
        form.classList.toggle("txn-type-commercial", type === "commercial");
    }
    document.querySelectorAll("[data-txn-section]").forEach(function (section) {
        const active = section.dataset.txnSection === type;
        section.classList.toggle("hidden", !active);
        section.querySelectorAll("input, select, textarea").forEach(function (field) {
            if (readonlyForm && field.tagName === "SELECT") {
                field.disabled = true;
            } else {
                field.disabled = !active;
            }
        });
    });

    document.querySelectorAll("[data-txn-type]").forEach(function (button) {
        button.classList.toggle("active", button.dataset.txnType === type);
    });

    // The Print Ticket banner belongs to the just-saved local transaction only.
    const ticketBanner = document.getElementById("ticketPrintBanner");
    if (ticketBanner) {
        ticketBanner.classList.toggle("hidden", type !== "local");
    }

    computePreview();
}

function printLocalTicket(url) {
    const errorBox = document.getElementById("ticketPrintError");
    const ticketWindow = window.open(url, "_blank");

    if (!ticketWindow || ticketWindow.closed || typeof ticketWindow.closed === "undefined") {
        if (errorBox) errorBox.classList.remove("hidden");
        return false;
    }

    if (errorBox) errorBox.classList.add("hidden");
    return true;
}

function preservedScrollKey() {
    return "palaykita:scroll:" + window.location.pathname + window.location.search;
}

function setupPreservedScrollForms() {
    document.querySelectorAll("form[data-preserve-scroll]").forEach(function (form) {
        form.addEventListener("submit", function () {
            try {
                sessionStorage.setItem(preservedScrollKey(), JSON.stringify({
                    x: window.pageXOffset || window.scrollX || 0,
                    y: window.pageYOffset || window.scrollY || 0
                }));
            } catch (error) {
                // Browsers can block sessionStorage; marking paid should still work.
            }
        });
    });
}

function restorePreservedScrollPosition() {
    let savedPosition = null;

    try {
        savedPosition = sessionStorage.getItem(preservedScrollKey());
        if (!savedPosition) return;
        sessionStorage.removeItem(preservedScrollKey());
    } catch (error) {
        return;
    }

    let position;
    try {
        position = JSON.parse(savedPosition);
    } catch (error) {
        position = { x: 0, y: Number(savedPosition) || 0 };
    }

    const x = Number(position.x || 0);
    const y = Number(position.y || 0);
    if (!Number.isFinite(x) || !Number.isFinite(y) || y <= 0) return;

    requestAnimationFrame(function () {
        window.scrollTo(x, y);
    });
}

document.addEventListener("click", function (event) {
    const typeButton = event.target.closest("[data-txn-type]");
    if (typeButton && !typeButton.disabled) {
        setTransactionType(typeButton.dataset.txnType);
        return;
    }

    const paymentButton = event.target.closest("[data-payment-open]");
    if (paymentButton && !paymentButton.disabled) {
        openPaymentModal(
            paymentButton.dataset.paymentId,
            paymentButton.dataset.paymentNumber,
            paymentButton.dataset.paymentType,
            paymentButton.dataset.paymentBalance
        );
    }
});

document.addEventListener("input", computePreview);
document.addEventListener("change", computePreview);
document.addEventListener("DOMContentLoaded", function () {
    const hidden = document.getElementById("transactionType");
    if (hidden) setTransactionType(hidden.value || "local");
    computePreview();
    setupPreservedScrollForms();
    restorePreservedScrollPosition();
});

function openPaymentModal(transactionId, transactionNumber, transactionType, balance) {
    const modal = document.getElementById("paymentModal");
    const form = document.getElementById("paymentForm");
    const label = document.getElementById("paymentTransaction");
    const balanceLabel = document.getElementById("paymentBalance");
    const amountInput = form ? form.querySelector("[name='payment_amount']") : null;

    if (!modal || !form) return;

    if (transactionType === "commercial") {
        form.action = `/commercial-transactions/${transactionId}/payment`;
    } else {
        form.action = `/transactions/${transactionId}/payment`;
    }
    if (label) label.textContent = transactionNumber;

    const outstanding = Number(balance);
    const hasBalance = Number.isFinite(outstanding) && outstanding > 0;

    if (balanceLabel) {
        balanceLabel.textContent = hasBalance ? "Outstanding balance: " + peso(outstanding) : "";
    }
    if (amountInput) {
        amountInput.value = "";
        if (hasBalance) {
            amountInput.max = outstanding.toFixed(2);
            amountInput.placeholder = outstanding.toFixed(2);
        } else {
            amountInput.removeAttribute("max");
            amountInput.placeholder = "";
        }
    }

    modal.classList.remove("hidden");
}

function closePaymentModal() {
    const modal = document.getElementById("paymentModal");
    if (modal) modal.classList.add("hidden");
}

function openCustomerModal() {
    const modal = document.getElementById("customerModal");
    if (modal) modal.classList.remove("hidden");
}

function closeCustomerModal() {
    const modal = document.getElementById("customerModal");
    if (modal) modal.classList.add("hidden");
}

document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
        closePaymentModal();
        closeCustomerModal();
    }
});


function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
            alert("Copied: " + text);
        }).catch(function () {
            fallbackCopyText(text);
        });
    } else {
        fallbackCopyText(text);
    }
}

function fallbackCopyText(text) {
    const temp = document.createElement("input");
    temp.value = text;
    document.body.appendChild(temp);
    temp.select();
    document.execCommand("copy");
    document.body.removeChild(temp);
    alert("Copied: " + text);
}

function togglePassword(button) {
    const wrapper = button.closest(".password-field");
    if (!wrapper) return;
    const input = wrapper.querySelector("input");
    if (!input) return;

    if (input.type === "password") {
        input.type = "text";
        button.textContent = "Hide";
    } else {
        input.type = "password";
        button.textContent = "Show";
    }
}

function generatePassword(formId) {
    const form = document.getElementById(formId);
    if (!form) return;

    const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$";
    let password = "PK-";
    for (let i = 0; i < 10; i++) {
        password += alphabet[Math.floor(Math.random() * alphabet.length)];
    }

    const passwordInputs = form.querySelectorAll("input[name='password'], input[name='confirm_password']");
    passwordInputs.forEach(function (input) {
        input.value = password;
        input.type = "text";
    });

    const showButtons = form.querySelectorAll(".password-field button");
    showButtons.forEach(function (button) {
        button.textContent = "Hide";
    });

    copyText(password);
}

// Stop mouse-wheel scrolling from accidentally changing number input values.
function preventNumberInputWheelChanges() {
    document.querySelectorAll('input[type="number"]').forEach(function (input) {
        input.addEventListener('wheel', function (event) {
            if (document.activeElement === input) {
                event.preventDefault();
            }
        }, { passive: false });
    });
}

document.addEventListener("DOMContentLoaded", preventNumberInputWheelChanges);

function setupFatherTributeModal() {
    const trigger = document.querySelector("[data-tribute-trigger]");
    const modal = document.getElementById("fatherTributeModal");
    if (!trigger || !modal) return;

    let tributeClicks = 0;
    const closeButtons = modal.querySelectorAll("[data-tribute-close]");

    function openTributeModal() {
        modal.hidden = false;
        const closeButton = modal.querySelector(".tribute-close");
        if (closeButton) closeButton.focus();
    }

    function closeTributeModal() {
        modal.hidden = true;
        trigger.focus();
    }

    trigger.addEventListener("click", function () {
        tributeClicks += 1;
        if (tributeClicks >= 5) {
            tributeClicks = 0;
            openTributeModal();
        }
    });

    closeButtons.forEach(function (button) {
        button.addEventListener("click", closeTributeModal);
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !modal.hidden) {
            closeTributeModal();
        }
    });
}

document.addEventListener("DOMContentLoaded", setupFatherTributeModal);
