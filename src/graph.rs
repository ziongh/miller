// Graph Processing Module
//
// High-performance graph algorithms for code analysis:
// - Transitive closure (BFS from all nodes in parallel)
// - PageRank for symbol importance scoring
//
// This module replaces the Python-based graph processing which was O(V * (V + E))
// with parallelized Rust using rayon, achieving O((V + E) / cores) practical performance.

use pyo3::prelude::*;
use petgraph::algo::kosaraju_scc;
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::visit::EdgeRef;
use rayon::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};
use std::collections::VecDeque;

/// Graph processor for computing transitive closure and PageRank.
///
/// Uses petgraph for the graph representation and rayon for parallel processing.
/// Designed to handle 100k+ nodes and 500k+ edges efficiently.
#[pyclass]
pub struct PyGraphProcessor {
    /// The directed graph structure
    graph: DiGraph<String, ()>,
    /// Fast lookup from node ID string to graph node index
    node_map: FxHashMap<String, NodeIndex>,
    /// Reverse lookup from node index to node ID string
    index_to_id: Vec<String>,
}

#[pymethods]
impl PyGraphProcessor {
    /// Create a new graph processor from a list of edges.
    ///
    /// Args:
    ///     edges: List of (from_id, to_id) tuples representing directed edges
    ///
    /// Example:
    ///     processor = GraphProcessor([("a", "b"), ("b", "c")])
    #[new]
    pub fn new(edges: Vec<(String, String)>) -> Self {
        let mut graph = DiGraph::new();
        let mut node_map: FxHashMap<String, NodeIndex> = FxHashMap::default();
        let mut index_to_id: Vec<String> = Vec::new();

        // First pass: collect all unique node IDs
        for (from_id, to_id) in &edges {
            if !node_map.contains_key(from_id) {
                let idx = graph.add_node(from_id.clone());
                node_map.insert(from_id.clone(), idx);
                index_to_id.push(from_id.clone());
            }
            if !node_map.contains_key(to_id) {
                let idx = graph.add_node(to_id.clone());
                node_map.insert(to_id.clone(), idx);
                index_to_id.push(to_id.clone());
            }
        }

        // Second pass: add all edges
        for (from_id, to_id) in edges {
            let from_idx = node_map[&from_id];
            let to_idx = node_map[&to_id];
            graph.add_edge(from_idx, to_idx, ());
        }

        PyGraphProcessor {
            graph,
            node_map,
            index_to_id,
        }
    }

    /// Number of nodes in the graph.
    #[getter]
    pub fn node_count(&self) -> usize {
        self.graph.node_count()
    }

    /// Number of edges in the graph.
    #[getter]
    pub fn edge_count(&self) -> usize {
        self.graph.edge_count()
    }

    /// Compute transitive closure using parallel BFS from each node.
    ///
    /// For each node in the graph, performs a BFS to find all reachable nodes
    /// within max_depth hops. The computation is parallelized across nodes
    /// using rayon.
    ///
    /// Args:
    ///     max_depth: Maximum path length to consider (default: 10)
    ///
    /// Returns:
    ///     List of (source_id, target_id, distance) tuples
    ///
    /// Complexity:
    ///     O((V + E) / cores) practical, vs O(V * (V + E)) in Python
    pub fn compute_closure(&self, max_depth: Option<usize>) -> Vec<(String, String, u32)> {
        let max_depth = max_depth.unwrap_or(10);
        let node_count = self.graph.node_count();

        if node_count == 0 {
            return Vec::new();
        }

        // Parallel BFS from each node
        let results: Vec<Vec<(String, String, u32)>> = (0..node_count)
            .into_par_iter()
            .map(|start_idx| {
                let start_node = NodeIndex::new(start_idx);
                self.bfs_from_node(start_node, max_depth)
            })
            .collect();

        // Flatten results
        results.into_iter().flatten().collect()
    }

    /// Compute PageRank scores for all nodes.
    ///
    /// Uses the iterative power method with damping factor.
    ///
    /// Args:
    ///     damping: Damping factor (default: 0.85, standard PageRank value)
    ///     iterations: Number of iterations (default: 100)
    ///
    /// Returns:
    ///     List of (node_id, score) tuples, scores normalized to 0-1 range
    pub fn compute_page_rank(
        &self,
        damping: Option<f64>,
        iterations: Option<usize>,
    ) -> Vec<(String, f64)> {
        let damping = damping.unwrap_or(0.85);
        let iterations = iterations.unwrap_or(100);
        let node_count = self.graph.node_count();

        if node_count == 0 {
            return Vec::new();
        }

        // Initialize scores uniformly
        let initial_score = 1.0 / node_count as f64;
        let mut scores: Vec<f64> = vec![initial_score; node_count];
        let mut new_scores: Vec<f64> = vec![0.0; node_count];

        // Precompute out-degrees for each node
        let out_degrees: Vec<usize> = (0..node_count)
            .map(|i| {
                self.graph
                    .edges(NodeIndex::new(i))
                    .count()
            })
            .collect();

        // Iterative PageRank computation
        let teleport = (1.0 - damping) / node_count as f64;

        for _ in 0..iterations {
            // Reset new scores
            new_scores.iter_mut().for_each(|s| *s = teleport);

            // Distribute scores along edges
            for source_idx in 0..node_count {
                let source_node = NodeIndex::new(source_idx);
                let out_degree = out_degrees[source_idx];

                if out_degree == 0 {
                    // Dangling node: distribute to all nodes
                    let contribution = damping * scores[source_idx] / node_count as f64;
                    for target_score in new_scores.iter_mut() {
                        *target_score += contribution;
                    }
                } else {
                    // Distribute to neighbors
                    let contribution = damping * scores[source_idx] / out_degree as f64;
                    for edge in self.graph.edges(source_node) {
                        let target_idx = edge.target().index();
                        new_scores[target_idx] += contribution;
                    }
                }
            }

            // Swap scores
            std::mem::swap(&mut scores, &mut new_scores);
        }

        // Normalize to 0-1 range
        let max_score = scores.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let min_score = scores.iter().cloned().fold(f64::INFINITY, f64::min);
        let range = max_score - min_score;

        let normalized: Vec<f64> = if range > 0.0 {
            scores.iter().map(|s| (s - min_score) / range).collect()
        } else {
            vec![0.5; node_count] // All equal
        };

        // Build result with node IDs
        self.index_to_id
            .iter()
            .enumerate()
            .map(|(idx, id)| (id.clone(), normalized[idx]))
            .collect()
    }

    /// Detect entry points (high in-degree, low out-degree).
    ///
    /// Entry points are symbols that are called by many others but don't
    /// call many functions themselves - typically API handlers, main(), etc.
    ///
    /// Returns:
    ///     List of (node_id, is_entry_point) tuples
    pub fn detect_entry_points(&self) -> Vec<(String, bool)> {
        let node_count = self.graph.node_count();

        if node_count == 0 {
            return Vec::new();
        }

        self.index_to_id
            .iter()
            .enumerate()
            .map(|(idx, id)| {
                let node = NodeIndex::new(idx);
                let in_degree = self.graph.neighbors_directed(node, petgraph::Direction::Incoming).count();
                let out_degree = self.graph.edges(node).count();

                // Entry point: called by at least 2 others, calls fewer than called by
                let is_entry = in_degree >= 2 && out_degree < in_degree;
                (id.clone(), is_entry)
            })
            .collect()
    }

    /// Get nodes with their in/out degrees.
    ///
    /// Useful for understanding graph structure and identifying hubs.
    ///
    /// Returns:
    ///     List of (node_id, in_degree, out_degree) tuples
    pub fn get_degrees(&self) -> Vec<(String, usize, usize)> {
        self.index_to_id
            .iter()
            .enumerate()
            .map(|(idx, id)| {
                let node = NodeIndex::new(idx);
                let in_degree = self.graph.neighbors_directed(node, petgraph::Direction::Incoming).count();
                let out_degree = self.graph.edges(node).count();
                (id.clone(), in_degree, out_degree)
            })
            .collect()
    }

    /// Check if a node exists in the graph.
    ///
    /// Args:
    ///     node_id: The node ID to check
    ///
    /// Returns:
    ///     True if the node exists
    pub fn contains_node(&self, node_id: &str) -> bool {
        self.node_map.contains_key(node_id)
    }

    /// Get all node IDs in the graph.
    ///
    /// Returns:
    ///     List of node ID strings
    pub fn get_nodes(&self) -> Vec<String> {
        self.index_to_id.clone()
    }

    /// Find dead code nodes using reachability from entry points.
    ///
    /// Dead code = nodes that are not reachable from any entry point.
    /// This detects:
    /// 1. Isolated nodes (no path from entry points)
    /// 2. Dead cycles ("islands") - e.g., A→B→A where nothing calls A or B
    ///
    /// Algorithm:
    /// 1. Start BFS from all entry points
    /// 2. Mark all reachable nodes as "live"
    /// 3. Return all nodes NOT marked as live
    ///
    /// Args:
    ///     entry_points: List of node IDs that are known entry points
    ///                   (e.g., main, test_*, handlers, *Controller)
    ///
    /// Returns:
    ///     List of node IDs that are structurally dead (unreachable from entry points)
    pub fn find_dead_nodes(&self, entry_points: Vec<String>) -> Vec<String> {
        let node_count = self.graph.node_count();
        if node_count == 0 {
            return Vec::new();
        }

        // Convert entry point names to node indices
        let entry_indices: Vec<NodeIndex> = entry_points
            .iter()
            .filter_map(|name| self.node_map.get(name).copied())
            .collect();

        // If no valid entry points, all nodes are considered dead
        if entry_indices.is_empty() {
            return self.index_to_id.clone();
        }

        // BFS from all entry points to find reachable nodes
        let mut reachable: FxHashSet<usize> = FxHashSet::default();
        let mut queue: VecDeque<NodeIndex> = VecDeque::new();

        // Seed with entry points
        for &entry in &entry_indices {
            reachable.insert(entry.index());
            queue.push_back(entry);
        }

        // BFS to find all reachable nodes
        while let Some(current) = queue.pop_front() {
            for edge in self.graph.edges(current) {
                let neighbor = edge.target();
                if !reachable.contains(&neighbor.index()) {
                    reachable.insert(neighbor.index());
                    queue.push_back(neighbor);
                }
            }
        }

        // Return all nodes NOT reachable from entry points
        self.index_to_id
            .iter()
            .enumerate()
            .filter(|(idx, _)| !reachable.contains(idx))
            .map(|(_, id)| id.clone())
            .collect()
    }

    /// Find dead cycles (islands of mutually-calling code).
    ///
    /// Returns SCCs with more than one node that are not reachable from entry points.
    /// These are groups of functions that only call each other but are never
    /// called from outside the group.
    ///
    /// Args:
    ///     entry_points: List of node IDs that are known entry points
    ///
    /// Returns:
    ///     List of (cycle_nodes, cycle_size) where cycle_nodes is a list of node IDs
    ///     that form a dead cycle, sorted by cycle size descending
    pub fn find_dead_cycles(&self, entry_points: Vec<String>) -> Vec<(Vec<String>, usize)> {
        let node_count = self.graph.node_count();
        if node_count == 0 {
            return Vec::new();
        }

        // First, find all reachable nodes from entry points
        let entry_indices: Vec<NodeIndex> = entry_points
            .iter()
            .filter_map(|name| self.node_map.get(name).copied())
            .collect();

        let mut reachable: FxHashSet<usize> = FxHashSet::default();
        let mut queue: VecDeque<NodeIndex> = VecDeque::new();

        for &entry in &entry_indices {
            reachable.insert(entry.index());
            queue.push_back(entry);
        }

        while let Some(current) = queue.pop_front() {
            for edge in self.graph.edges(current) {
                let neighbor = edge.target();
                if !reachable.contains(&neighbor.index()) {
                    reachable.insert(neighbor.index());
                    queue.push_back(neighbor);
                }
            }
        }

        // Compute SCCs
        let sccs = kosaraju_scc(&self.graph);

        // Find dead cycles (SCCs with size > 1 where NO node is reachable)
        let mut dead_cycles: Vec<(Vec<String>, usize)> = Vec::new();

        for scc in &sccs {
            // Only interested in cycles (size > 1)
            if scc.len() <= 1 {
                continue;
            }

            // Check if any node in this SCC is reachable
            let is_reachable = scc.iter().any(|&node| reachable.contains(&node.index()));

            if is_reachable {
                continue;
            }

            // This is a dead cycle - all nodes are unreachable
            let cycle_nodes: Vec<String> = scc
                .iter()
                .map(|&node| self.index_to_id[node.index()].clone())
                .collect();
            let cycle_size = cycle_nodes.len();
            dead_cycles.push((cycle_nodes, cycle_size));
        }

        // Sort by size descending (largest dead cycles first)
        dead_cycles.sort_by(|a, b| b.1.cmp(&a.1));

        dead_cycles
    }

    /// Get nodes with zero incoming edges (potential orphans).
    ///
    /// These are simpler to detect than dead cycles - just nodes with in_degree = 0.
    /// For comprehensive dead code detection, use find_dead_nodes which also
    /// catches dead cycles.
    ///
    /// Returns:
    ///     List of node IDs with no incoming edges
    pub fn find_orphan_nodes(&self) -> Vec<String> {
        self.index_to_id
            .iter()
            .enumerate()
            .filter(|(idx, _)| {
                let node = NodeIndex::new(*idx);
                self.graph
                    .neighbors_directed(node, petgraph::Direction::Incoming)
                    .next()
                    .is_none()
            })
            .map(|(_, id)| id.clone())
            .collect()
    }
}

impl PyGraphProcessor {
    /// BFS from a single node, returning reachability tuples.
    fn bfs_from_node(&self, start: NodeIndex, max_depth: usize) -> Vec<(String, String, u32)> {
        let start_id = &self.index_to_id[start.index()];

        // Check if this node has any outgoing edges
        if self.graph.edges(start).next().is_none() {
            return Vec::new();
        }

        let mut results = Vec::new();
        let mut visited: FxHashMap<NodeIndex, u32> = FxHashMap::default();
        let mut queue: VecDeque<(NodeIndex, u32)> = VecDeque::new();

        visited.insert(start, 0);
        queue.push_back((start, 0));

        while let Some((current, depth)) = queue.pop_front() {
            if depth >= max_depth as u32 {
                continue;
            }

            for edge in self.graph.edges(current) {
                let neighbor = edge.target();
                if !visited.contains_key(&neighbor) {
                    let new_depth = depth + 1;
                    visited.insert(neighbor, new_depth);
                    queue.push_back((neighbor, new_depth));

                    let target_id = &self.index_to_id[neighbor.index()];
                    results.push((start_id.clone(), target_id.clone(), new_depth));
                }
            }
        }

        results
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_graph() {
        let processor = PyGraphProcessor::new(vec![]);
        assert_eq!(processor.node_count(), 0);
        assert_eq!(processor.edge_count(), 0);
        assert!(processor.compute_closure(None).is_empty());
        assert!(processor.compute_page_rank(None, None).is_empty());
    }

    #[test]
    fn test_simple_chain() {
        // A -> B -> C
        let edges = vec![
            ("a".to_string(), "b".to_string()),
            ("b".to_string(), "c".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        assert_eq!(processor.node_count(), 3);
        assert_eq!(processor.edge_count(), 2);

        let closure = processor.compute_closure(Some(10));

        // Should have: A->B(1), A->C(2), B->C(1)
        assert_eq!(closure.len(), 3);

        // Check specific paths exist
        let has_a_to_b = closure.iter().any(|(s, t, d)| s == "a" && t == "b" && *d == 1);
        let has_a_to_c = closure.iter().any(|(s, t, d)| s == "a" && t == "c" && *d == 2);
        let has_b_to_c = closure.iter().any(|(s, t, d)| s == "b" && t == "c" && *d == 1);

        assert!(has_a_to_b, "Missing a->b path");
        assert!(has_a_to_c, "Missing a->c path");
        assert!(has_b_to_c, "Missing b->c path");
    }

    #[test]
    fn test_cycle_handling() {
        // A -> B -> C -> A (cycle)
        let edges = vec![
            ("a".to_string(), "b".to_string()),
            ("b".to_string(), "c".to_string()),
            ("c".to_string(), "a".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        // Should complete without infinite loop
        let closure = processor.compute_closure(Some(10));

        // Each node can reach all others
        let has_a_to_b = closure.iter().any(|(s, t, _)| s == "a" && t == "b");
        let has_a_to_c = closure.iter().any(|(s, t, _)| s == "a" && t == "c");
        let has_b_to_a = closure.iter().any(|(s, t, _)| s == "b" && t == "a");
        let has_c_to_a = closure.iter().any(|(s, t, _)| s == "c" && t == "a");

        assert!(has_a_to_b);
        assert!(has_a_to_c);
        assert!(has_b_to_a);
        assert!(has_c_to_a);
    }

    #[test]
    fn test_max_depth_limit() {
        // Long chain: A -> B -> C -> D -> E
        let edges = vec![
            ("a".to_string(), "b".to_string()),
            ("b".to_string(), "c".to_string()),
            ("c".to_string(), "d".to_string()),
            ("d".to_string(), "e".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let closure = processor.compute_closure(Some(2));

        // A can reach B(1) and C(2) but NOT D(3) or E(4)
        let has_a_to_b = closure.iter().any(|(s, t, d)| s == "a" && t == "b" && *d == 1);
        let has_a_to_c = closure.iter().any(|(s, t, d)| s == "a" && t == "c" && *d == 2);
        let has_a_to_d = closure.iter().any(|(s, t, _)| s == "a" && t == "d");
        let has_a_to_e = closure.iter().any(|(s, t, _)| s == "a" && t == "e");

        assert!(has_a_to_b);
        assert!(has_a_to_c);
        assert!(!has_a_to_d, "Should NOT reach D with max_depth=2");
        assert!(!has_a_to_e, "Should NOT reach E with max_depth=2");
    }

    #[test]
    fn test_diamond_pattern() {
        // Diamond: A -> B, A -> C, B -> D, C -> D
        let edges = vec![
            ("a".to_string(), "b".to_string()),
            ("a".to_string(), "c".to_string()),
            ("b".to_string(), "d".to_string()),
            ("c".to_string(), "d".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let closure = processor.compute_closure(Some(10));

        // A can reach D (shortest path is 2)
        let a_to_d = closure.iter().find(|(s, t, _)| s == "a" && t == "d");
        assert!(a_to_d.is_some());
        assert_eq!(a_to_d.unwrap().2, 2);
    }

    #[test]
    fn test_disconnected_components() {
        // Two disconnected chains: A -> B and C -> D
        let edges = vec![
            ("a".to_string(), "b".to_string()),
            ("c".to_string(), "d".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let closure = processor.compute_closure(Some(10));

        // A can reach B, C can reach D
        let has_a_to_b = closure.iter().any(|(s, t, _)| s == "a" && t == "b");
        let has_c_to_d = closure.iter().any(|(s, t, _)| s == "c" && t == "d");

        // A cannot reach C or D
        let has_a_to_c = closure.iter().any(|(s, t, _)| s == "a" && t == "c");
        let has_a_to_d = closure.iter().any(|(s, t, _)| s == "a" && t == "d");

        assert!(has_a_to_b);
        assert!(has_c_to_d);
        assert!(!has_a_to_c);
        assert!(!has_a_to_d);
    }

    #[test]
    fn test_pagerank_basic() {
        // Simple graph: A -> B, A -> C, B -> C
        let edges = vec![
            ("a".to_string(), "b".to_string()),
            ("a".to_string(), "c".to_string()),
            ("b".to_string(), "c".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let pagerank = processor.compute_page_rank(None, None);

        assert_eq!(pagerank.len(), 3);

        // C should have highest score (most incoming links)
        let scores: std::collections::HashMap<_, _> = pagerank.into_iter().collect();
        assert!(scores["c"] > scores["a"], "C should rank higher than A");
        assert!(scores["c"] > scores["b"], "C should rank higher than B");
    }

    #[test]
    fn test_entry_points() {
        // A and B call C, C calls D
        let edges = vec![
            ("a".to_string(), "c".to_string()),
            ("b".to_string(), "c".to_string()),
            ("c".to_string(), "d".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let entry_points = processor.detect_entry_points();
        let entries: std::collections::HashMap<_, _> = entry_points.into_iter().collect();

        // C has in_degree=2, out_degree=1, so it's an entry point
        assert!(entries["c"], "C should be an entry point");

        // A, B have in_degree=0, so they're not entry points
        assert!(!entries["a"]);
        assert!(!entries["b"]);
    }

    #[test]
    fn test_degrees() {
        let edges = vec![
            ("a".to_string(), "b".to_string()),
            ("a".to_string(), "c".to_string()),
            ("b".to_string(), "c".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let degrees = processor.get_degrees();
        let degree_map: std::collections::HashMap<_, _> = degrees
            .into_iter()
            .map(|(id, in_d, out_d)| (id, (in_d, out_d)))
            .collect();

        assert_eq!(degree_map["a"], (0, 2)); // A: 0 incoming, 2 outgoing
        assert_eq!(degree_map["b"], (1, 1)); // B: 1 incoming, 1 outgoing
        assert_eq!(degree_map["c"], (2, 0)); // C: 2 incoming, 0 outgoing
    }

    // ==================== Dead Code Detection Tests ====================

    #[test]
    fn test_find_dead_nodes_simple_orphan() {
        // main -> A, B is orphan (no one calls B)
        let edges = vec![
            ("main".to_string(), "a".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        // Add B as an isolated node by having it call something
        // Actually, B won't be in the graph if it has no edges
        // Let's create a better test case

        let edges = vec![
            ("main".to_string(), "a".to_string()),
            ("b".to_string(), "c".to_string()),  // B -> C, but no one calls B
        ];
        let processor = PyGraphProcessor::new(edges);

        let dead = processor.find_dead_nodes(vec!["main".to_string()]);

        // B and C should be dead (no path from main)
        assert!(dead.contains(&"b".to_string()), "B should be dead");
        assert!(dead.contains(&"c".to_string()), "C should be dead");
        // main and A should NOT be dead
        assert!(!dead.contains(&"main".to_string()), "main should not be dead");
        assert!(!dead.contains(&"a".to_string()), "A should not be dead");
    }

    #[test]
    fn test_find_dead_nodes_dead_cycle() {
        // The "Island Problem" - A and B call each other but no one calls them
        // main -> X, A <-> B (dead cycle)
        let edges = vec![
            ("main".to_string(), "x".to_string()),
            ("a".to_string(), "b".to_string()),
            ("b".to_string(), "a".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let dead = processor.find_dead_nodes(vec!["main".to_string()]);

        // A and B form a dead cycle - both should be dead
        assert!(dead.contains(&"a".to_string()), "A should be dead (part of dead cycle)");
        assert!(dead.contains(&"b".to_string()), "B should be dead (part of dead cycle)");
        // main and X should NOT be dead
        assert!(!dead.contains(&"main".to_string()));
        assert!(!dead.contains(&"x".to_string()));
    }

    #[test]
    fn test_find_dead_nodes_live_cycle() {
        // A cycle that IS reachable from entry point is NOT dead
        // main -> A -> B -> A (cycle)
        let edges = vec![
            ("main".to_string(), "a".to_string()),
            ("a".to_string(), "b".to_string()),
            ("b".to_string(), "a".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let dead = processor.find_dead_nodes(vec!["main".to_string()]);

        // No dead code - the cycle is reachable
        assert!(!dead.contains(&"a".to_string()), "A should NOT be dead");
        assert!(!dead.contains(&"b".to_string()), "B should NOT be dead");
    }

    #[test]
    fn test_find_dead_nodes_multiple_entry_points() {
        // Multiple entry points - different parts of graph are live
        // main1 -> A, main2 -> B, C is orphan
        let edges = vec![
            ("main1".to_string(), "a".to_string()),
            ("main2".to_string(), "b".to_string()),
            ("c".to_string(), "d".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let dead = processor.find_dead_nodes(vec!["main1".to_string(), "main2".to_string()]);

        // C and D should be dead
        assert!(dead.contains(&"c".to_string()));
        assert!(dead.contains(&"d".to_string()));
        // A and B should NOT be dead
        assert!(!dead.contains(&"a".to_string()));
        assert!(!dead.contains(&"b".to_string()));
    }

    #[test]
    fn test_find_dead_nodes_empty_entry_points() {
        // If no entry points specified, all nodes with in_degree=0 are roots
        let edges = vec![
            ("a".to_string(), "b".to_string()),
            ("b".to_string(), "c".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        // With no entry points, "a" has in_degree=0 so its SCC is a root
        let dead = processor.find_dead_nodes(vec![]);

        // All nodes should be dead since no entry points
        assert_eq!(dead.len(), 3, "All 3 nodes should be dead with no entry points");
    }

    #[test]
    fn test_find_dead_cycles() {
        // Find specifically the dead cycles (not orphans)
        let edges = vec![
            ("main".to_string(), "x".to_string()),
            // Dead cycle 1: A <-> B
            ("a".to_string(), "b".to_string()),
            ("b".to_string(), "a".to_string()),
            // Dead cycle 2: C -> D -> E -> C
            ("c".to_string(), "d".to_string()),
            ("d".to_string(), "e".to_string()),
            ("e".to_string(), "c".to_string()),
            // Orphan (not a cycle): F -> G
            ("f".to_string(), "g".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let dead_cycles = processor.find_dead_cycles(vec!["main".to_string()]);

        // Should find 2 dead cycles
        assert_eq!(dead_cycles.len(), 2, "Should find 2 dead cycles");

        // Larger cycle first (C-D-E has size 3)
        let (cycle1, size1) = &dead_cycles[0];
        assert_eq!(*size1, 3);
        assert!(cycle1.contains(&"c".to_string()));
        assert!(cycle1.contains(&"d".to_string()));
        assert!(cycle1.contains(&"e".to_string()));

        // Smaller cycle second (A-B has size 2)
        let (cycle2, size2) = &dead_cycles[1];
        assert_eq!(*size2, 2);
        assert!(cycle2.contains(&"a".to_string()));
        assert!(cycle2.contains(&"b".to_string()));
    }

    #[test]
    fn test_find_orphan_nodes() {
        // Simple in_degree=0 detection
        let edges = vec![
            ("a".to_string(), "b".to_string()),
            ("c".to_string(), "d".to_string()),
            ("b".to_string(), "d".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let orphans = processor.find_orphan_nodes();

        // A and C have in_degree=0
        assert!(orphans.contains(&"a".to_string()));
        assert!(orphans.contains(&"c".to_string()));
        // B and D have incoming edges
        assert!(!orphans.contains(&"b".to_string()));
        assert!(!orphans.contains(&"d".to_string()));
    }

    #[test]
    fn test_find_dead_nodes_complex_graph() {
        // Complex graph with multiple components
        //
        // main -> A -> B -> C
        //              |
        //              v
        //              D (leaf)
        //
        // X -> Y (dead component, X is orphan)
        //
        // P <-> Q (dead cycle)
        //
        let edges = vec![
            ("main".to_string(), "a".to_string()),
            ("a".to_string(), "b".to_string()),
            ("b".to_string(), "c".to_string()),
            ("b".to_string(), "d".to_string()),
            // Dead component
            ("x".to_string(), "y".to_string()),
            // Dead cycle
            ("p".to_string(), "q".to_string()),
            ("q".to_string(), "p".to_string()),
        ];
        let processor = PyGraphProcessor::new(edges);

        let dead = processor.find_dead_nodes(vec!["main".to_string()]);

        // Live nodes (reachable from main)
        assert!(!dead.contains(&"main".to_string()));
        assert!(!dead.contains(&"a".to_string()));
        assert!(!dead.contains(&"b".to_string()));
        assert!(!dead.contains(&"c".to_string()));
        assert!(!dead.contains(&"d".to_string()));

        // Dead nodes
        assert!(dead.contains(&"x".to_string()), "X should be dead");
        assert!(dead.contains(&"y".to_string()), "Y should be dead");
        assert!(dead.contains(&"p".to_string()), "P should be dead");
        assert!(dead.contains(&"q".to_string()), "Q should be dead");
    }
}
