/**
* Merge lines into a string with padding
*/
function stringifyFactoryIconCodeLines(lines, padding = 0) {
	const pad = "  ".repeat(padding);
	return lines.map((line) => pad + line).join("\n");
}
export { stringifyFactoryIconCodeLines };
