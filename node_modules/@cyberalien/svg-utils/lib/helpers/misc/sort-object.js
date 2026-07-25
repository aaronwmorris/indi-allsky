/**
* Sort object keys to generate consistend JSON output
*
* Used to hash objects
*/
function sortObject(data) {
	if (typeof data !== "object" || data === null) return data;
	if (Array.isArray(data)) return data.map(sortObject);
	if (data instanceof Set) {
		const values = Array.from(data).map(sortObject);
		values.sort();
		return new Set(values);
	}
	const keys = Object.keys(data);
	keys.sort();
	const newObject = Object.create(null);
	for (const key of keys) newObject[key] = sortObject(data[key]);
	return newObject;
}
export { sortObject };
