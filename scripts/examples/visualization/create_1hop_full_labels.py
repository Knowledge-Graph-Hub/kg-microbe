#!/usr/bin/env python3
import os
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import math
from config import CATEGORY_COLORS

def create_1hop_full_labels():
    """Create 1-hop visualization with full node labels"""

    # Get script directory for relative paths
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Load data
    nodes_df = pd.read_csv(os.path.join(script_dir, 'corynebacterium_glutamicum_1hop_subgraph_nodes.csv'))
    edges_df = pd.read_csv(os.path.join(script_dir, 'corynebacterium_glutamicum_1hop_subgraph_edges.csv'))
    
    center_id = "NCBITaxon:1718"
    
    # Create NetworkX graph
    G = nx.Graph()
    
    # Add nodes
    for _, node in nodes_df.iterrows():
        G.add_node(node['id'], 
                  name=node['name'], 
                  category=node['category'], 
                  hop=node['hop'])
    
    # Add edges
    for _, edge in edges_df.iterrows():
        if edge['subject'] in G.nodes and edge['object'] in G.nodes:
            G.add_edge(edge['subject'], edge['object'])
    
    # Create layout optimized for 1-hop with multiple rings
    pos = {}
    center_pos = (0, 0)
    pos[center_id] = center_pos
    
    # Get neighbors and organize them by category for better layout
    neighbors = [n for n in G.nodes() if G.nodes[n]['hop'] == 1]
    
    # Organize neighbors by category
    category_groups = {}
    for neighbor in neighbors:
        categories = str(G.nodes[neighbor]['category']).split('|') if G.nodes[neighbor]['category'] else ['unknown']
        primary_category = categories[0]
        if primary_category not in category_groups:
            category_groups[primary_category] = []
        category_groups[primary_category].append(neighbor)
    
    # Arrange in concentric rings by category
    radius_start = 6
    radius_increment = 3
    current_radius = radius_start
    
    for category, nodes_in_category in category_groups.items():
        nodes_count = len(nodes_in_category)
        
        for i, neighbor in enumerate(nodes_in_category):
            angle = 2 * math.pi * i / nodes_count
            pos[neighbor] = (current_radius * math.cos(angle), current_radius * math.sin(angle))
        
        current_radius += radius_increment
    
    # Create very large figure to accommodate full labels
    plt.figure(figsize=(40, 40))

    # Use shared category color configuration
    category_colors = CATEGORY_COLORS

    # Draw center node
    center_categories = str(G.nodes[center_id]['category']).split('|') if G.nodes[center_id]['category'] else ['unknown']
    center_color = category_colors.get(center_categories[0], '#CCCCCC')
    
    nx.draw_networkx_nodes(G, pos, nodelist=[center_id], 
                          node_color=[center_color], 
                          node_size=[12000],
                          alpha=0.9,
                          edgecolors='black',
                          linewidths=4)
    
    # Draw 1-hop neighbors by category
    for category, nodes_in_category in category_groups.items():
        color = category_colors.get(category, '#CCCCCC')
        nx.draw_networkx_nodes(G, pos, nodelist=nodes_in_category, 
                              node_color=[color] * len(nodes_in_category), 
                              node_size=[6000] * len(nodes_in_category),
                              alpha=0.8,
                              edgecolors='black',
                              linewidths=2)
    
    # Draw edges with different styles
    nx.draw_networkx_edges(G, pos, alpha=0.4, width=3, edge_color='gray')
    
    # Create FULL labels for ALL nodes - no truncation at all
    labels = {}
    
    # Center node label
    center_name = str(G.nodes[center_id]['name']) if G.nodes[center_id]['name'] else center_id
    labels[center_id] = center_name
    
    # ALL 1-hop neighbors with COMPLETELY FULL names
    for neighbor in neighbors:
        name = str(G.nodes[neighbor]['name']) if G.nodes[neighbor]['name'] else neighbor
        # Show the COMPLETE name with no truncation whatsoever
        labels[neighbor] = name
    
    # Draw labels with enhanced formatting
    nx.draw_networkx_labels(G, pos, labels, font_size=10, font_weight='bold', 
                           font_color='black', 
                           bbox=dict(boxstyle='round,pad=0.5', 
                           facecolor='white', alpha=0.95, edgecolor='gray', linewidth=1))
    
    # Add title
    plt.title(f'1-Hop Subgraph: {center_name} - COMPLETE FULL LABELS\n({len(G.nodes)} nodes, {len(G.edges)} edges)', 
              fontsize=28, fontweight='bold', pad=80)
    
    # Add comprehensive legend
    legend_elements = []
    for category, color in category_colors.items():
        if category in category_groups:
            count = len(category_groups[category])
            legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                            markerfacecolor=color, markersize=18, 
                                            label=f'{category.replace("biolink:", "")} ({count})'))
    
    # Add hop legend
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=25, 
                                    label='Center (Corynebacterium glutamicum)'))
    
    plt.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1), 
              fontsize=16, frameon=True, fancybox=True, shadow=True, 
              title='Node Categories', title_fontsize=18)
    
    # Remove axes
    plt.axis('off')
    
    # Adjust layout and save
    plt.tight_layout()
    output_file = os.path.join(script_dir, 'corynebacterium_glutamicum_1hop_subgraph_full_labels.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    plt.show()

    print(f"1-hop visualization with complete full labels saved to {output_file}")
    print(f"Total labels shown: {len(labels)}")
    print(f"Categories represented: {list(category_groups.keys())}")

if __name__ == "__main__":
    create_1hop_full_labels()