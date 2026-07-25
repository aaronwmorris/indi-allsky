import { writeFile } from "node:fs/promises";

/**
* Write JSON file
*/
async function writeJSONFile(filename, data) {
	return writeFile(filename, JSON.stringify(data, null, "	") + "\n");
}

export { writeJSONFile };