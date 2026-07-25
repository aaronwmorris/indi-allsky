/**
* Generate fallback string from template and states
*/
function getIconFallback(template, values, defaultValues) {
	const stateValue = (state) => values[state] ?? defaultValues?.[state];
	return template.map((chunk) => typeof chunk === "string" ? chunk : "values" in chunk ? chunk.values[+!!stateValue(chunk.state)] : stateValue(chunk.state)).join("");
}
export { getIconFallback };
