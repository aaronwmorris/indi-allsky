const safeProps = [
	"width",
	"height",
	"focus",
	"square",
	"action",
	"mode",
	"align",
	"halign",
	"valign"
];
/**
* Clean up common properties in component content
*/
function cleanupJSXRenamedProps(content) {
	for (const prop of safeProps) {
		const match = `${prop}: ${prop}Prop,`;
		if (content.includes(match)) content = content.replaceAll(match, `${prop},`).replaceAll(`${prop}Prop`, prop);
	}
	return content;
}
export { cleanupJSXRenamedProps };
