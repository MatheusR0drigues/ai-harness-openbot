# Implementation Plan

- [ ] 1. Export command
  - [ ] 1.1 Write failing tests for the export command
    - _Requirements: 1.1, 1.2_
  - [ ] 1.2 Implement the export command
    - _Requirements: 1.1, 1.2_
    - _Depends on: 1.1_

- [ ] 2. Size limit and compression
  - _Requirements: 2_
  - [ ] 2.1 Stop the export at 100 MB
    - _Requirements: 2.1_
    - _Depends on: 1.2_
  - [ ]* 2.2 Compress the output with gzip
    - _Requirements: 2.2_
    - _Depends on: 2.1_
