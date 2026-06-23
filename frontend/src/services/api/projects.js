// Projects & Environments (Workspace -> Project -> Environment -> Applications)
//
// Project endpoints are workspace-scoped; the active workspace is derived from
// the X-Workspace-Id header the client already sends, so these methods don't
// need to pass it explicitly.

// --- Projects ---

export async function getProjects() {
    return this.request('/projects');
}

export async function getProject(id) {
    return this.request(`/projects/${id}`);
}

export async function createProject(data) {
    return this.request('/projects', {
        method: 'POST',
        body: data,
    });
}

export async function updateProject(id, data) {
    return this.request(`/projects/${id}`, {
        method: 'PUT',
        body: data,
    });
}

export async function deleteProject(id) {
    return this.request(`/projects/${id}`, {
        method: 'DELETE',
    });
}

// --- Environments ---

export async function createEnvironment(projectId, data) {
    return this.request('/environments', {
        method: 'POST',
        body: { project_id: projectId, ...data },
    });
}

export async function updateEnvironment(environmentId, data) {
    return this.request(`/environments/${environmentId}`, {
        method: 'PUT',
        body: data,
    });
}

export async function deleteEnvironment(environmentId) {
    return this.request(`/environments/${environmentId}`, {
        method: 'DELETE',
    });
}

export async function reorderEnvironments(projectId, orderedIds) {
    return this.request('/environments/reorder', {
        method: 'POST',
        body: { project_id: projectId, ordered_ids: orderedIds },
    });
}
