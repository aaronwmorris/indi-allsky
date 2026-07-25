/**
* Parse viewBox string to IconViewBox
*/
function parseViewBox(value) {
	const parts = value.split(/[\s,]+/).map((item) => item.trim());
	if (parts.length !== 4) return;
	const nums = parts.map((part) => Number(part));
	if (nums.some((num) => isNaN(num))) return;
	return {
		left: nums[0],
		top: nums[1],
		width: nums[2],
		height: nums[3]
	};
}
export { parseViewBox };
