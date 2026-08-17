(() => {
    const form = document.getElementById("ppp-form");
    const sourceSelect = document.getElementById("source_country");
    const targetSelect = document.getElementById("target_country");
    const salaryInput = document.getElementById("salary");
    const output = document.getElementById("output");
    const summary = document.getElementById("summary");
    const errorBox = document.getElementById("error");
    const calculateBtn = document.getElementById("calculate-btn");

    // Only one calculation should ever be in flight; the button is
    // disabled while a request is pending, but this token also guards
    // against a stale response landing after a newer one already did.
    let requestToken = 0;

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
        summary.hidden = true;
        output.value = "";
    }

    function clearMessages() {
        errorBox.hidden = true;
        summary.hidden = true;
    }

    function setLoading(isLoading) {
        calculateBtn.disabled = isLoading;
        calculateBtn.textContent = isLoading ? "Calculating..." : "Calculate";
    }

    async function runConversion() {
        const source_country = sourceSelect.value;
        const target_country = targetSelect.value;
        const salary = salaryInput.value.trim();

        if (!source_country || !target_country || !salary) {
            showError("Please choose both countries and enter a salary.");
            return;
        }

        const currentToken = ++requestToken;
        setLoading(true);

        try {
            const response = await fetch("/api/convert", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ source_country, target_country, salary }),
            });

            const data = await response.json();

            if (currentToken !== requestToken) return;

            if (!response.ok) {
                showError(data.error || "Something went wrong.");
                return;
            }

            clearMessages();
            output.value = data.equivalent_salary;
            summary.hidden = false;
            summary.innerHTML =
                `You require a salary of <strong>${data.equivalent_salary}</strong> in ` +
                `${data.target_country}'s local currency to live a similar quality of life ` +
                `as you would with a salary of <strong>${data.source_salary}</strong> in ` +
                `${data.source_country}'s local currency. (World Bank PPP data, ${data.data_year})`;
        } catch (err) {
            if (currentToken !== requestToken) return;
            showError("Could not reach the server. Please try again.");
        } finally {
            if (currentToken === requestToken) setLoading(false);
        }
    }

    // Submit fires on button click and on Enter inside the form,
    // covering the calculate action from a single handler.
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        runConversion();
    });
})();