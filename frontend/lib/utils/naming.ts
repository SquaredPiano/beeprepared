const nouns = ['Hive', 'Cell', 'Swarm', 'Nectar', 'Pollen', 'Worker', 'Drone', 'Queen', 'Comb', 'Wax', 'Honey', 'Petal', 'Meadow', 'Garden', 'Bloom', 'Grove', 'Forest', 'Mountain', 'River', 'Sea', 'Sky', 'Star', 'Cloud', 'Dawn', 'Dusk'];
const adjectives = ['Golden', 'Busy', 'Sweet', 'Sharp', 'Bright', 'Amber', 'Warm', 'Deep', 'Pure', 'Wild', 'Gentle', 'Strong', 'Quiet', 'Active', 'Strategic', 'Architectural', 'Intelligent', 'Radiant', 'Sturdy', 'Vast', 'Eternal', 'Crystal', 'Lush', 'Fluent', 'Cognitive'];
const verbs = ['Synthesizing', 'Extracting', 'Building', 'Growing', 'Collecting', 'Guarding', 'Dancing', 'Flying', 'Mapping', 'Preparing', 'Refining', 'Polishing', 'Brewing', 'Scanning', 'Analyzing', 'Solving', 'Creating', 'Weaving', 'Flowing', 'Sparking'];

export function generateProjectName() {
  const adj = adjectives[Math.floor(Math.random() * adjectives.length)];
  const noun = nouns[Math.floor(Math.random() * nouns.length)];
  const verb = verbs[Math.floor(Math.random() * verbs.length)];
  
  const patterns = [
    `${adj} ${noun}`,
    `${verb} ${noun}`,
    `${adj} ${verb} ${noun}`,
    `The ${adj} ${noun}`
  ];
  
  return patterns[Math.floor(Math.random() * patterns.length)];
}
