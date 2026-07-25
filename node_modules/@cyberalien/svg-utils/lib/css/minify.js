function minifyCSS(value) {
	return value.replace(/\s+/g, " ").replace(/\s*([;:{}])\s*/g, "$1").replace(/;}/g, "}").trim();
}
export { minifyCSS };
