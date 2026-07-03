// Doctor / drift API — health sweep + configuration drift surface
// (Monitoring → Doctor tab). Admin-only endpoints under /api/v1/doctor.

export async function getDoctorReport() {
    return this.request('/doctor');
}

export async function runDoctor() {
    return this.request('/doctor/run', { method: 'POST' });
}

export async function repairDoctorItems(items) {
    return this.request('/doctor/repair', {
        method: 'POST',
        body: JSON.stringify({ items }),
    });
}

export async function getDriftReport() {
    return this.request('/doctor/drift');
}

export async function runDriftCheck() {
    return this.request('/doctor/drift/check', { method: 'POST' });
}

export async function repairDrift(type, id) {
    return this.request(`/doctor/drift/${type}/${id}/repair`, {
        method: 'POST',
        body: JSON.stringify({ confirm: true }),
    });
}
