// .htaccess -> nginx converter (/api/v1/apps/htaccess-convert).
// Pure text transform: paste Apache .htaccess rules, get nginx directives
// suitable for the per-site custom nginx rules box, plus notes and a list
// of directives that could not be translated.

export async function convertHtaccess(htaccessText) {
    return this.request('/apps/htaccess-convert', {
        method: 'POST',
        body: { htaccess: htaccessText },
    });
}
