/**
* Axios config, customisable
*/
const axiosConfig = {};
/**
* Customisable callbacks, used for logging
*/
const fetchCallbacks = { onStart: (url) => console.log("Fetching:", url) };

export { axiosConfig, fetchCallbacks };