import { createContext, useContext } from "solid-js";
import { createStore } from "solid-js/store";

const API_HOST = typeof window !== "undefined"
  ? (window.location.port === "5173" || window.location.port === "3000" ? `${window.location.hostname}:8000` : window.location.host)
  : "127.0.0.1:8000";
const httpProtocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "https://" : "http://";

export const AppContext = createContext();

export function AppProvider(props) {
  const [state, setState] = createStore({
    projects: [],
    selectedProjectId: null,
    projectDetails: null,
    isLoading: false,
  });

  const actions = {
      // --- ACTIONS ---
      async fetchProjects() {
        try {
          setState("isLoading", true);
          const res = await fetch(`${httpProtocol}${API_HOST}/api/projects`);
          if (res.ok) {
            const data = await res.json();
            setState("projects", data);
            if (data.length > 0 && !state.selectedProjectId) {
              actions.selectProject(data[0].id);
            }
          }
        } catch (e) {
          console.error("Failed to load projects", e);
        } finally {
          setState("isLoading", false);
        }
      },

      async fetchProjectDetails(projectId) {
        if (!projectId) {
          setState("projectDetails", null);
          return;
        };
        try {
          setState("isLoading", true);
          const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${projectId}`);
          if (res.ok) {
            const data = await res.json();
            setState("projectDetails", data);
          }
        } catch (e) {
          console.error("Failed to fetch project details", e);
        } finally {
          setState("isLoading", false);
        }
      },

      selectProject(projectId) {
        setState("selectedProjectId", projectId);
        actions.fetchProjectDetails(projectId);
      },

      async deleteProject(projectId) {
        if (!confirm("Are you sure you want to permanently delete this project? All processed data will be wiped.")) return;
        try {
          const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${projectId}`, {
            method: "DELETE"
          });
          if (res.ok) {
            alert("Project deleted successfully!");
            // Reselect if the deleted project was the active one
            if (state.selectedProjectId === projectId) {
              setState("selectedProjectId", null);
              setState("projectDetails", null);
            }
            actions.fetchProjects(); // Refresh the list
          } else {
            const data = await res.json();
            alert(`Failed to delete: ${data.detail}`);
          }
        } catch (e) {
          alert(`Error deleting: ${e.message}`);
        }
      },

      async cancelProject(projectId) {
        if (!confirm("Are you sure you want to stop/cancel this translation job?")) return;
        const res = await fetch(`${httpProtocol}${API_HOST}/api/projects/${projectId}/cancel`, {
          method: "POST"
        });
        if (res.ok) alert("Pipeline cancel request sent!");
        actions.fetchProjects(); // Refresh the list
      }
  };

  const store = [state, actions];

  return (
    <AppContext.Provider value={store}>
      {props.children}
    </AppContext.Provider>
  );
}

export const useAppContext = () => useContext(AppContext);